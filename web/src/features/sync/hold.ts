/**
 * A drag owns the screen: refetched cards would move under the pointer. While a hold is on, the
 * updates wait here and run on release.
 */
let held = false;
const waiting = new Set<() => void>();

export function holdUpdates(): void {
  held = true;
}

export function releaseUpdates(): void {
  held = false;
  const updates = [...waiting];
  waiting.clear();
  for (const update of updates) update();
}

export function whenReleased(update: () => void): void {
  if (held) waiting.add(update);
  else update();
}
