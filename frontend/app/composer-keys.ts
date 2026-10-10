type EnterKeyEvent = { key: string; shiftKey: boolean; keyCode?: number; nativeEvent?: { isComposing?: boolean } };

export function shouldSubmitOnEnter(event: EnterKeyEvent, text: string, busy: boolean) {
  if (event.key !== "Enter" || event.shiftKey) return false;
  if (event.nativeEvent?.isComposing || event.keyCode === 229) return false;
  return !busy && text.trim().length > 0;
}
