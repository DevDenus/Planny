"""Manual live evaluation of the assistant against the real LLM and STT servers.

    uv run python scripts/assistant_eval.py [--only text|voice] [--case 6] [--repeat 3] [--out FILE]

Text cases go through the same path as production (build_messages, chat/completions with the
json_schema response format, normalize). Voice cases synthesize the phrases with Piper, send them
as Ogg/Opus to the STT server, then run the transcript through that path. It is a report, not a
gate: the exit code is always 0. Needs no database and no API.
"""

import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

from assistant_eval_cases import CASES, Case, View, make_context, to_view

from app.assistant.normalize import normalize
from app.assistant.prompt import RESPONSE_FORMAT, Context, build_messages
from app.assistant.schemas import Card

LLM_URL = os.environ.get("EVAL_LLM_URL", "http://192.168.0.105:8081/v1")
STT_URL = os.environ.get("EVAL_STT_URL", "http://192.168.0.105:8082/v1")
STT_MODEL = "Systran/faster-whisper-medium"
CACHE = Path(__file__).resolve().parent.parent / ".eval-cache"
VOICES = ("ru_RU-irina-medium", "ru_RU-denis-medium", "ru_RU-dmitri-medium")
VARIANTS = ("clean", "noise", "fast")
VOICE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU"
FFMPEG = "/usr/bin/ffmpeg"
NOISE_DB = -28.0


# ---------------------------------------------------------------- pipeline


@dataclass
class Turn:
    text: str
    raw: dict[str, Any] | None
    card: dict[str, Any] | None
    reply: str
    warnings: list[str]
    llm_seconds: float
    error: str | None = None


@dataclass
class Run:
    turns: list[Turn] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    passed_checks: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def ask_llm(client: httpx.Client, messages: list[dict[str, str]]) -> dict[str, Any]:
    body = {
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 800,
        "response_format": RESPONSE_FORMAT,
    }
    response = client.post(f"{LLM_URL}/chat/completions", json=body)
    response.raise_for_status()
    raw = json.loads(response.json()["choices"][0]["message"]["content"])
    if not isinstance(raw, dict):
        raise ValueError("answer is not an object")
    return raw


def run_pipeline(
    client: httpx.Client,
    ctx: Context,
    case: Case,
    last_text: str | None,
    latencies: list[float],
) -> Run:
    """Play the turns of the case; `last_text` replaces the final turn (a transcript)."""
    run = Run()
    texts = list(case.turns)
    if last_text is not None:
        texts[-1] = last_text
    current: Card | None = case.initial(ctx) if case.initial else None
    history: list[str] = []
    warnings: list[str] = []
    for text in texts:
        started = time.monotonic()
        raw: dict[str, Any] | None = None
        try:
            messages = build_messages(ctx, text, history, current)
            raw = ask_llm(client, messages)
            latency = time.monotonic() - started
            latencies.append(latency)
            outcome = normalize(raw, ctx, current, case.locked)  # type: ignore[arg-type]
        except Exception as exc:  # a report must survive any single failure
            run.turns.append(Turn(text, raw, None, "", [], time.monotonic() - started, repr(exc)))
            run.failed.append("error")
            return run
        current, warnings = outcome.card, outcome.warnings
        history.append(text)
        run.turns.append(
            Turn(
                text,
                raw,
                current.model_dump(mode="json") if current else None,
                outcome.reply,
                warnings,
                latency,
            )
        )
    view: View = to_view(current, ctx, warnings)
    for name, predicate in case.checks:
        if predicate(view):
            run.passed_checks.append(name)
        else:
            run.failed.append(name)
    return run


# ---------------------------------------------------------------- audio


def sh(*args: str | Path) -> str:
    done = subprocess.run(  # noqa: S603
        [str(a) for a in args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {done.stderr[-400:]}")
    return done.stderr + done.stdout


def piper_python() -> Path:
    venv = CACHE / "piper-venv"
    python = venv / "bin" / "python"
    if not python.exists():
        uv = shutil.which("uv") or "uv"
        sh(uv, "venv", "--python", "3.12", venv)
        sh(uv, "pip", "install", "--python", python, "piper-tts")
    return python


def voice_model(voice: str) -> Path:
    directory = CACHE / "voices"
    directory.mkdir(parents=True, exist_ok=True)
    name = voice.split("-")[1]
    for suffix in (".onnx", ".onnx.json"):
        target = directory / f"{voice}{suffix}"
        if not target.exists():
            url = f"{VOICE_BASE}/{name}/medium/{voice}{suffix}"
            response = httpx.get(url, follow_redirects=True, timeout=300)
            response.raise_for_status()
            target.write_bytes(response.content)
    return directory / f"{voice}.onnx"


def mean_volume(path: Path) -> float:
    out = sh(FFMPEG, "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-")
    match = re.search(r"mean_volume: (-?[0-9.]+) dB", out)
    return float(match.group(1)) if match else -20.0


def noise_gain_db(speech: Path, directory: Path) -> float:
    """Gain that puts the generated pink noise NOISE_DB below the speech, by mean volume."""
    sample = directory / "pink-reference.wav"
    if not sample.exists():
        sh(
            FFMPEG, "-y", "-f", "lavfi", "-i",
            "anoisesrc=color=pink:amplitude=0.5:sample_rate=22050:duration=5", sample,
        )  # fmt: skip
    return mean_volume(speech) + NOISE_DB - mean_volume(sample)


def audio_file(case: Case, voice: str, variant: str) -> Path:
    directory = CACHE / "audio"
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"case{case.id:02d}-{voice}"
    wav = directory / f"{stem}.wav"
    text_stamp = directory / f"{stem}.txt"
    if not wav.exists() or not text_stamp.exists() or text_stamp.read_text() != case.text:
        for old in directory.glob(f"{stem}-*.ogg"):
            old.unlink()
        sh(piper_python(), "-m", "piper", "-m", voice_model(voice), "-f", wav, "--", case.text)
        text_stamp.write_text(case.text)
    ogg = directory / f"{stem}-{variant}.ogg"
    if ogg.exists():
        return ogg
    encode: list[str | Path] = ["-ac", "1", "-c:a", "libopus", "-b:a", "32k", ogg]
    if variant == "clean":
        sh(FFMPEG, "-y", "-i", wav, *encode)
    elif variant == "fast":
        sh(FFMPEG, "-y", "-i", wav, "-filter:a", "atempo=1.15", *encode)
    else:
        gain = noise_gain_db(wav, directory)
        graph = f"[1:a]volume={gain:.1f}dB[n];[0:a][n]amix=inputs=2:duration=first:normalize=0[o]"
        sh(
            FFMPEG, "-y", "-i", wav, "-f", "lavfi", "-i",
            "anoisesrc=color=pink:amplitude=0.5:sample_rate=22050:duration=30",
            "-filter_complex", graph, "-map", "[o]", *encode,
        )  # fmt: skip
    return ogg


def transcribe(client: httpx.Client, path: Path) -> tuple[str, float]:
    started = time.monotonic()
    response = client.post(
        f"{STT_URL}/audio/transcriptions",
        files={"file": (path.name, path.read_bytes(), "audio/ogg")},
        data={"model": STT_MODEL, "language": "ru", "response_format": "json"},
    )
    response.raise_for_status()
    return str(response.json()["text"]).strip(), time.monotonic() - started


# ---------------------------------------------------------------- metrics


def words(text: str) -> list[str]:
    return re.sub(r"[^\w]+", " ", text.lower().replace("ё", "е")).split()


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = words(reference), words(hypothesis)
    if not ref:
        return 0.0
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        row = [i]
        for j, h in enumerate(hyp, 1):
            row.append(min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + (r != h)))
        previous = row
    return previous[-1] / len(ref)


def keyword_hits(transcript: str, keywords: tuple[str, ...]) -> int:
    cleaned = " ".join(words(transcript))
    return sum(1 for k in keywords if re.search(k.replace("ё", "е"), cleaned))


def percentile(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


# ---------------------------------------------------------------- evaluation


def run_to_json(run: Run) -> dict[str, Any]:
    return {
        "ok": run.ok,
        "failed": run.failed,
        "passed": run.passed_checks,
        "turns": [vars(t) for t in run.turns],
    }


def eval_text(
    client: httpx.Client, ctx: Context, cases: list[Case], repeat: int, lat: list[float]
) -> list[dict[str, Any]]:
    print("\n== TEXT ==")
    print(f"{'case':<5}{'passed':<8}failed checks")
    results = []
    for case in cases:
        runs = [run_pipeline(client, ctx, case, None, lat) for _ in range(repeat)]
        fails: dict[str, int] = {}
        for run in runs:
            for name in run.failed:
                fails[name] = fails.get(name, 0) + 1
        detail = ", ".join(f"{n} {c}/{repeat}" for n, c in fails.items()) or "-"
        passed = sum(run.ok for run in runs)
        print(f"{case.id:<5}{f'{passed}/{repeat}':<8}{detail}", flush=True)
        results.append(
            {
                "case": case.id,
                "turns": list(case.turns),
                "passed": passed,
                "repeat": repeat,
                "field_failures": fails,
                "runs": [run_to_json(r) for r in runs],
            }
        )
    return results


def eval_voice(
    client: httpx.Client,
    stt: httpx.Client,
    ctx: Context,
    cases: list[Case],
    repeat: int,
    llm_lat: list[float],
    stt_lat: list[float],
) -> list[dict[str, Any]]:
    print("\n== VOICE ==")
    print(f"{'case':<5}{'voice':<22}{'variant':<8}{'WER':<7}{'kw':<6}pipeline")
    results = []
    for case in cases:
        if case.keywords is None:
            continue
        for voice in VOICES:
            for variant in VARIANTS:
                row: dict[str, Any] = {"case": case.id, "voice": voice, "variant": variant}
                try:
                    path = audio_file(case, voice, variant)
                    transcript, seconds = transcribe(stt, path)
                except Exception as exc:
                    print(f"{case.id:<5}{voice:<22}{variant:<8}error: {exc!r}"[:150], flush=True)
                    row["error"] = repr(exc)
                    results.append(row)
                    continue
                stt_lat.append(seconds)
                error = wer(case.text, transcript)
                hits = keyword_hits(transcript, case.keywords)
                runs = [run_pipeline(client, ctx, case, transcript, llm_lat) for _ in range(repeat)]
                passed = sum(r.ok for r in runs)
                total = len(case.keywords)
                print(
                    f"{case.id:<5}{voice:<22}{variant:<8}{error:<7.2f}{f'{hits}/{total}':<6}"
                    f"{passed}/{repeat}  {transcript!r}"[:150],
                    flush=True,
                )
                row |= {
                    "transcript": transcript,
                    "reference": case.text,
                    "wer": error,
                    "keywords_hit": hits,
                    "keywords_total": total,
                    "stt_seconds": seconds,
                    "passed": passed,
                    "repeat": repeat,
                    "runs": [run_to_json(r) for r in runs],
                }
                results.append(row)
    return results


def summary(text: list[dict[str, Any]], voice: list[dict[str, Any]], llm: list[float],
            stt: list[float]) -> None:  # fmt: skip
    print("\n== SUMMARY ==")
    if text:
        done = sum(r["passed"] for r in text)
        total = sum(r["repeat"] for r in text)
        print(f"text pass rate: {done}/{total} = {done / total:.0%}")
        by_field: dict[str, int] = {}
        for r in text:
            for name, count in r["field_failures"].items():
                key = f"case {r['case']} {name}"
                by_field[key] = by_field.get(key, 0) + count
        if by_field:
            print("failed fields: " + ", ".join(f"{k} x{v}" for k, v in by_field.items()))
    good = [r for r in voice if "wer" in r]
    if good:
        for variant in VARIANTS:
            rows = [r for r in good if r["variant"] == variant]
            if rows:
                mean = statistics.fmean(r["wer"] for r in rows)
                kw = sum(r["keywords_hit"] for r in rows) / sum(r["keywords_total"] for r in rows)
                done = sum(r["passed"] for r in rows)
                total = sum(r["repeat"] for r in rows)
                print(
                    f"voice {variant:<6} mean WER {mean:.3f}  keyword recall {kw:.0%}  "
                    f"pipeline {done}/{total} = {done / total:.0%}"
                )
        done = sum(r["passed"] for r in good)
        total = sum(r["repeat"] for r in good)
        print(f"voice pipeline pass rate overall: {done}/{total} = {done / total:.0%}")
    errors = len(voice) - len(good)
    if errors:
        print(f"voice rows with errors: {errors}")
    for name, values in (("LLM", llm), ("STT", stt)):
        if values:
            print(
                f"{name} latency s: p50 {percentile(values, 0.5):.2f}  "
                f"p95 {percentile(values, 0.95):.2f}  n={len(values)}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("text", "voice"))
    parser.add_argument("--case", type=int, action="append", help="case number, repeatable")
    parser.add_argument("--repeat", type=int, default=3, help="runs per text case")
    parser.add_argument("--voice-repeat", type=int, default=1, help="pipeline runs per audio")
    parser.add_argument("--out", type=Path, help="report file or directory")
    args = parser.parse_args()

    started = time.monotonic()
    ctx = make_context()
    cases = [c for c in CASES if not args.case or c.id in args.case]
    llm_lat: list[float] = []
    stt_lat: list[float] = []
    text: list[dict[str, Any]] = []
    voice: list[dict[str, Any]] = []
    timeout = httpx.Timeout(180)
    with httpx.Client(timeout=timeout) as llm, httpx.Client(timeout=timeout) as stt:
        if args.only != "voice":
            text = eval_text(llm, ctx, cases, args.repeat, llm_lat)
        if args.only != "text":
            voice = eval_voice(llm, stt, ctx, cases, args.voice_repeat, llm_lat, stt_lat)
    summary(text, voice, llm_lat, stt_lat)
    elapsed = time.monotonic() - started
    print(f"elapsed: {elapsed:.0f} s")

    stamp = datetime.now(ZoneInfo("UTC")).strftime("%Y%m%d-%H%M%S")
    out: Path = args.out or CACHE / "reports"
    if out.suffix != ".json":
        out = out / f"{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "llm_url": LLM_URL,
                "stt_url": STT_URL,
                "elapsed_seconds": elapsed,
                "llm_latencies": llm_lat,
                "stt_latencies": stt_lat,
                "text": text,
                "voice": voice,
            },
            ensure_ascii=False,
            indent=1,
        )
    )
    print(f"report: {out}")


if __name__ == "__main__":
    main()
