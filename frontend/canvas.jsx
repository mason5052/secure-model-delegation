import React from "react";
import { createRoot } from "react-dom/client";
import { Excalidraw, exportToBlob, exportToSvg, restore, serializeAsJSON } from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";

window.EXCALIDRAW_ASSET_PATH = "/static/canvas/";
let canvasAPI = null;
const host = document.getElementById("canvas-host");
const ready = new Promise((resolve) => {
  class CanvasBoundary extends React.Component {
    constructor(props) { super(props); this.state = { failed: false }; }
    static getDerivedStateFromError() { return { failed: true }; }
    render() {
      return this.state.failed
        ? <p role="alert">The drawing editor could not start. Reopen the app and try again.</p>
        : this.props.children;
    }
  }
  createRoot(host).render(<CanvasBoundary><Excalidraw
    excalidrawAPI={(api) => { canvasAPI = api; resolve(); }}
    initialData={{ appState: { viewBackgroundColor: "#ffffff", currentItemFontFamily: 2 } }}
    UIOptions={{ canvasActions: { loadScene: true, saveToActiveFile: false, export: false, saveAsImage: false, toggleTheme: false } }}
    autoFocus={false}
    theme="light"
  /></CanvasBoundary>);
});

window.smdCanvas = {
  async export(format) {
    await ready;
    const elements = canvasAPI.getSceneElements();
    const appState = { ...canvasAPI.getAppState(), exportWithDarkMode: false, exportBackground: true };
    const files = canvasAPI.getFiles();
    if (format === "json") {
      return { blob: new Blob([serializeAsJSON(elements, appState, files, "local")], { type: "application/json" }), name: "drawing.excalidraw" };
    }
    if (format === "png") return { blob: await exportToBlob({ elements, appState, files, mimeType: "image/png" }), name: "drawing.png" };
    if (format === "svg") {
      const svg = await exportToSvg({ elements, appState, files, exportWithDarkMode: false });
      return { blob: new Blob([svg.outerHTML], { type: "image/svg+xml" }), name: "drawing.svg" };
    }
    throw new Error("Choose drawing, PNG, or SVG export.");
  },
  async open(text) {
    await ready;
    const input = JSON.parse(text);
    if (input.type !== "excalidraw" || !Array.isArray(input.elements)) throw new Error("Choose an Excalidraw drawing file.");
    const scene = restore(input, null, null);
    canvasAPI.updateScene(scene);
    if (input.files) canvasAPI.addFiles(Object.values(input.files));
  },
};
