import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { failureMessage } from "../tasks/api";
import { transcribe } from "./api";

export const MAX_RECORDING_SECONDS = 120;
const MIME_TYPES = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
const NO_MICROPHONE = "Нет доступа к микрофону";

export type VoiceState = "idle" | "recording" | "transcribing";

function pickType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return MIME_TYPES.find((type) => MediaRecorder.isTypeSupported?.(type));
}

function transcribeError(error: unknown): string {
  if (error instanceof ApiError && error.status === 503) return "Распознавание недоступно";
  if (error instanceof ApiError && error.status === 413) return "Запись слишком длинная";
  return failureMessage(error);
}

/** Records the microphone into memory and turns it into text. Nothing is stored anywhere. */
export function useVoiceInput(onText: (text: string) => void) {
  const [state, setState] = useState<VoiceState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string>();
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const elapsed = useRef(0);
  const discard = useRef(false);
  const alive = useRef(true);
  const starting = useRef(false);
  const onTextRef = useRef(onText);

  useEffect(() => {
    onTextRef.current = onText;
  }, [onText]);

  const release = useCallback(() => {
    window.clearInterval(timer.current);
    timer.current = undefined;
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  }, []);

  const finish = useCallback(
    async (chunks: Blob[], type: string) => {
      release();
      recorder.current = null;
      if (discard.current || !alive.current) {
        setState("idle");
        return;
      }
      setState("transcribing");
      try {
        const text = (await transcribe(new Blob(chunks, { type }))).trim();
        if (alive.current && text) onTextRef.current(text);
      } catch (failure) {
        if (alive.current) setError(transcribeError(failure));
      } finally {
        if (alive.current) setState("idle");
      }
    },
    [release],
  );

  const stop = useCallback(() => {
    if (recorder.current?.state === "recording") recorder.current.stop();
  }, []);

  const cancel = useCallback(() => {
    discard.current = true;
    if (recorder.current?.state === "recording") recorder.current.stop();
    else release();
    setState("idle");
  }, [release]);

  const start = useCallback(async () => {
    // A second press while the browser asks for the microphone would open a second stream.
    if (starting.current || recorder.current) return;
    starting.current = true;
    setError(undefined);
    discard.current = false;
    let media: MediaStream;
    try {
      media = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      if (alive.current) setError(NO_MICROPHONE);
      return;
    } finally {
      starting.current = false;
    }
    if (!alive.current) {
      // The page was left while the browser asked: the microphone must not stay on.
      media.getTracks().forEach((track) => track.stop());
      return;
    }
    stream.current = media;
    const wanted = pickType();
    let instance: MediaRecorder;
    try {
      instance = new MediaRecorder(media, wanted ? { mimeType: wanted } : undefined);
    } catch {
      release();
      setError(NO_MICROPHONE);
      return;
    }
    const chunks: Blob[] = [];
    instance.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    instance.onstop = () => void finish(chunks, instance.mimeType || wanted || "audio/webm");
    recorder.current = instance;
    instance.start();
    setSeconds(0);
    setState("recording");
    elapsed.current = 0;
    timer.current = window.setInterval(() => {
      elapsed.current += 1;
      setSeconds(elapsed.current);
      if (elapsed.current >= MAX_RECORDING_SECONDS && recorder.current?.state === "recording") {
        recorder.current.stop();
      }
    }, 1000);
  }, [finish, release]);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      discard.current = true;
      if (recorder.current?.state === "recording") recorder.current.stop();
      release();
    };
  }, [release]);

  return { state, seconds, error, start, stop, cancel };
}
