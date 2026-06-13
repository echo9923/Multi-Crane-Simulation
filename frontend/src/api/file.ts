// Read a Blob/File as text. Uses Blob.text() when available (real browsers)
// and falls back to FileReader for environments (jsdom) that lack it.

export function fileText(file: Blob): Promise<string> {
  const f = file as { text?: () => Promise<string> };
  if (typeof f.text === "function") return f.text();
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result));
    fr.onerror = () => reject(fr.error ?? new Error("FileReader error"));
    fr.readAsText(file);
  });
}
