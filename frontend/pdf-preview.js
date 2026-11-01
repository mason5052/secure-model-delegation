import { getDocument, GlobalWorkerOptions } from "pdfjs-dist/build/pdf.mjs";
GlobalWorkerOptions.workerSrc = "/static/pdf/pdf.worker.mjs";
const viewers = new WeakMap();
const element = (tag, cls, text) => {
  const item = document.createElement(tag);
  if (cls) item.className = cls;
  if (text !== undefined) item.textContent = String(text);
  return item;
};

export async function renderPdf(container, bytes) {
  if (viewers.has(container)) await viewers.get(container)();
  container.replaceChildren(element("p", "field-help", "Opening the locally rendered PDF..."));
  container.hidden = false;
  const task = getDocument({ data: bytes, isEvalSupported: false, useSystemFonts: true,
    cMapUrl: "/static/pdf/cmaps/", cMapPacked: true,
    standardFontDataUrl: "/static/pdf/standard_fonts/", wasmUrl: "/static/pdf/wasm/" });
  const pdf = await task.promise;
  let currentPage = 1;
  let rendering = null;
  let disposed = false;
  const toolbar = element("div", "pdf-toolbar");
  const previous = element("button", "button secondary small-button", "Previous");
  const next = element("button", "button secondary small-button", "Next");
  const counter = element("span", "mono");
  counter.setAttribute("aria-live", "polite");
  const zoom = element("select"); zoom.setAttribute("aria-label", "PDF zoom");
  for (const [value, label] of [["fit", "Fit width"], ["0.75", "75%"], ["1", "100%"], ["1.25", "125%"], ["1.5", "150%"]]) {
    const option = element("option", "", label); option.value = value; zoom.append(option);
  }
  const surface = element("div", "pdf-surface");
  const canvas = element("canvas", "pdf-page"); canvas.setAttribute("role", "img");
  surface.append(canvas);
  const details = element("details", "pdf-text");
  details.append(element("summary", "", "Page text"));
  const text = element("pre"); details.append(text);
  toolbar.append(previous, next, counter, zoom);
  container.replaceChildren(toolbar, surface, details);

  async function display() {
    if (disposed) return;
    previous.disabled = true; next.disabled = true; zoom.disabled = true;
    const page = await pdf.getPage(currentPage);
    const base = page.getViewport({ scale: 1 });
    const scale = zoom.value === "fit" ? Math.max(0.25, Math.min(2, (surface.clientWidth - 48) / base.width)) : Number(zoom.value);
    const viewport = page.getViewport({ scale });
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(viewport.width * ratio); canvas.height = Math.round(viewport.height * ratio);
    canvas.style.width = `${Math.round(viewport.width)}px`; canvas.style.height = `${Math.round(viewport.height)}px`;
    canvas.setAttribute("aria-label", `PDF page ${currentPage} of ${pdf.numPages}`);
    const context = canvas.getContext("2d", { alpha: false });
    rendering = page.render({ canvas, canvasContext: context, viewport, transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0] });
    await rendering.promise;
    const content = await page.getTextContent();
    text.textContent = content.items.map((item) => item.str + (item.hasEOL ? "\n" : " ")).join("");
    counter.textContent = `${currentPage} / ${pdf.numPages}`;
    previous.disabled = currentPage === 1; next.disabled = currentPage === pdf.numPages; zoom.disabled = false;
  }
  const run = () => display().catch((error) => { if (!disposed) container.append(element("p", "error", "This PDF page could not be rendered. Download the document to inspect it.")); });
  previous.addEventListener("click", () => { if (currentPage > 1) { currentPage--; run(); } });
  next.addEventListener("click", () => { if (currentPage < pdf.numPages) { currentPage++; run(); } });
  zoom.addEventListener("change", run);
  viewers.set(container, async () => { disposed = true; if (rendering) rendering.cancel(); await task.destroy(); });
  await display();
}
