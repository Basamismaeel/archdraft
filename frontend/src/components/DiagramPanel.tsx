import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

mermaid.initialize({
  startOnLoad: false,
  securityLevel: "strict",
  theme: "neutral",
  htmlLabels: true,
  layout: "elk",
  fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
  flowchart: { curve: "basis", padding: 10, nodeSpacing: 40, rankSpacing: 55, wrappingWidth: 260 },
});

let renderCounter = 0;
const RUN_TAG = Math.random().toString(36).slice(2, 8);
const MIN_READABLE_SCALE = 0.6;

interface Props {
  title: string;
  subtitle?: string;
  source: string | null;
  nodeIds: Record<string, string>; // Mermaid node ID -> element ID
  selected: string | null;
  highlighted: Set<string> | null;
  running: boolean;
  runningView?: React.ReactNode; // shown instead of the plain timer while running
  error: string | null;
  emptyHint: string;
  onSelect?: (elementId: string | null) => void;
  onRenderStatus?: (ok: boolean) => void;
}

function useElapsedSeconds(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) return;
    const started = Date.now();
    setSeconds(0);
    const timer = window.setInterval(() => setSeconds(Math.round((Date.now() - started) / 1000)), 500);
    return () => window.clearInterval(timer);
  }, [active]);
  return seconds;
}

const ACCENT = "#1f5fd1";
const ACCENT_SOFT = "#e8effc";

function setEmphasis(node: Element, on: boolean) {
  node.querySelectorAll<SVGElement>(":scope > :is(rect, path, polygon, circle, ellipse)").forEach((shape) => {
    if (shape.dataset.baseStyle === undefined) shape.dataset.baseStyle = shape.getAttribute("style") ?? "";
    shape.setAttribute("style", shape.dataset.baseStyle);
    if (on) {
      shape.style.setProperty("stroke", ACCENT, "important");
      shape.style.setProperty("stroke-width", "3px", "important");
      shape.style.setProperty("fill", ACCENT_SOFT, "important");
    }
  });
}

function elementIdOf(node: Element, nodeIds: Record<string, string>): string | null {
  const dataId = node.getAttribute("data-id");
  if (dataId && nodeIds[dataId]) return nodeIds[dataId];
  const match = node.id.match(/flowchart-(.+)-\d+$/);
  return match && nodeIds[match[1]] ? nodeIds[match[1]] : null;
}

export function DiagramPanel(props: Props) {
  const { source, nodeIds, selected, highlighted, running, onSelect, onRenderStatus } = props;
  const canvas = useRef<HTMLDivElement>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [renderTick, setRenderTick] = useState(0);
  const [zoom, setZoom] = useState<number | null>(null); // null = fit to panel
  const elapsed = useElapsedSeconds(running);

  // Render Mermaid source to SVG whenever it changes.
  useEffect(() => {
    const target = canvas.current;
    if (!target) return;
    target.innerHTML = "";
    setRenderError(null);
    if (!source) return;
    let cancelled = false;
    // Mermaid deletes any existing DOM element with the same ID, so IDs must never repeat,
    // even across hot reloads that reset the counter.
    const id = `mmd-${RUN_TAG}-${++renderCounter}`;
    mermaid
      .render(id, source)
      .then(({ svg, bindFunctions }) => {
        if (cancelled) return;
        target.innerHTML = svg;
        bindFunctions?.(target);
        // Large diagrams squeezed to the panel width become unreadable. Open them at a
        // readable minimum scale with scrolling instead; "Fit" still shows the whole picture.
        const rendered = target.querySelector("svg");
        const natural = rendered?.viewBox.baseVal?.width ?? 0;
        const available = target.parentElement?.clientWidth ?? 0;
        setZoom(natural > 0 && available / natural < MIN_READABLE_SCALE ? MIN_READABLE_SCALE : null);
        setRenderTick((t) => t + 1);
        onRenderStatus?.(true);
      })
      .catch((err: unknown) => {
        document.getElementById(`d${id}`)?.remove(); // Mermaid leaves an error SVG in <body>
        if (cancelled) return;
        setRenderError(err instanceof Error ? err.message : String(err));
        onRenderStatus?.(false);
      });
    return () => {
      cancelled = true;
    };
    // Re-render only when the source changes; onRenderStatus is a callback prop.
  }, [source]);

  // Selection and requirement highlighting. Mermaid writes classDef styles inline with
  // !important, which no stylesheet can override, so the emphasis is set inline as well.
  useEffect(() => {
    const target = canvas.current;
    if (!target) return;
    target.querySelectorAll("g.node").forEach((node) => {
      const elementId = elementIdOf(node, nodeIds);
      const emphasised =
        elementId !== null && (elementId === selected || (!!highlighted && highlighted.has(elementId)));
      node.classList.toggle("is-clickable", elementId !== null && !!onSelect);
      node.classList.toggle("is-dimmed", !!highlighted && !emphasised);
      setEmphasis(node, emphasised);
    });
  }, [renderTick, selected, highlighted, nodeIds, onSelect]);

  // Zoom: "fit" keeps Mermaid's responsive width; a number sets an explicit pixel width.
  useEffect(() => {
    const svg = canvas.current?.querySelector("svg");
    if (!svg) return;
    const natural = svg.viewBox.baseVal?.width || svg.getBoundingClientRect().width;
    if (zoom === null) {
      svg.setAttribute("width", "100%");
      svg.style.maxWidth = `${natural}px`;
    } else {
      svg.setAttribute("width", `${Math.round(natural * zoom)}`);
      svg.style.maxWidth = "none";
    }
    svg.removeAttribute("height");
    // Start a scrollable diagram at its horizontal centre, where the system boundary sits.
    const body = canvas.current?.parentElement;
    if (body) body.scrollLeft = Math.max(0, (body.scrollWidth - body.clientWidth) / 2);
  }, [zoom, renderTick]);

  function handleClick(event: React.MouseEvent<HTMLDivElement>) {
    if (!onSelect) return;
    const node = (event.target as Element).closest("g.node");
    onSelect(node ? elementIdOf(node, nodeIds) : null);
  }

  const showEmpty = !source && !running && !props.error;
  return (
    <section className="panel diagram-panel" aria-label={props.title}>
      <header className="panel-header">
        <div>
          <h2>{props.title}</h2>
          {props.subtitle && <p className="muted small">{props.subtitle}</p>}
        </div>
        {source && !renderError && (
          <div className="zoom-controls" role="group" aria-label="Zoom">
            <button type="button" onClick={() => setZoom((z) => Math.max(0.4, (z ?? 1) - 0.25))}>
              −
            </button>
            <button type="button" onClick={() => setZoom(null)} aria-pressed={zoom === null}>
              Fit
            </button>
            <button type="button" onClick={() => setZoom((z) => Math.min(3, (z ?? 1) + 0.25))}>
              +
            </button>
          </div>
        )}
      </header>
      <div className="diagram-body">
        {running &&
          (props.runningView ?? (
            <div className="diagram-status">
              Running… {elapsed} s
            </div>
          ))}
        {props.error && !running && <div className="diagram-status error-text">{props.error}</div>}
        {showEmpty && <div className="diagram-status muted">{props.emptyHint}</div>}
        {renderError && !running && (
          <div className="render-error">
            <strong>This diagram does not render.</strong> Mermaid rejected the generated code:
            <pre>{renderError}</pre>
            <details>
              <summary>Generated code</summary>
              <pre>{source}</pre>
            </details>
          </div>
        )}
        <div
          ref={canvas}
          className="diagram-canvas"
          hidden={running || !!renderError}
          onClick={handleClick}
        />
      </div>
    </section>
  );
}
