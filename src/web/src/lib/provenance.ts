// Provenance of a summary: which passage of the ruling each sentence rests on.
// Everything here tolerates missing fields, so summaries written before the trace existed still render.

import type { Summary, SummarySentence, SummarySource } from "./api";

export type Range = [number, number];

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Where a source passage sits in the ruling text: its offsets if they fit the quote, else the quote searched. */
export function locate(text: string, source: SummarySource): Range | null {
  const quote = (source.quote ?? "").trim();
  const { start, end } = source;
  const inRange = typeof start === "number" && typeof end === "number" && start >= 0 && end > start && end <= text.length;
  if (inRange && (!quote || text.slice(start, end).trim() === quote)) return [start, end];
  if (quote) {
    const at = text.indexOf(quote);
    if (at >= 0) return [at, at + quote.length];
    try {
      // The same words with different spacing or line breaks.
      const match = new RegExp(quote.split(/\s+/).map(escapeRegExp).join("\\s+")).exec(text);
      if (match) return [match.index, match.index + match[0].length];
    } catch {
      // a quote too long for a pattern: fall through
    }
  }
  return inRange ? [start, end] : null;
}

/** Ranges in reading order, overlaps joined. */
export function merge(ranges: Range[]): Range[] {
  const sorted = [...ranges].sort((a, b) => a[0] - b[0]);
  const out: Range[] = [];
  for (const [start, end] of sorted) {
    const last = out[out.length - 1];
    if (last && start <= last[1]) last[1] = Math.max(last[1], end);
    else out.push([start, end]);
  }
  return out;
}

export const sentencesOf = (summary: Summary | null | undefined): SummarySentence[] =>
  Array.isArray(summary?.sentences) ? summary.sentences.filter((s) => s && typeof s.text === "string") : [];

export const isRemoved = (sentence: SummarySentence) => sentence.status === "removed";

/** True when there is something to show for a sentence: a consideration, a source or a reason. */
export const hasTrace = (s: SummarySentence) =>
  (s.considerations?.length ?? 0) > 0 || (s.sources?.length ?? 0) > 0 || (s.why_not?.length ?? 0) > 0;

/** A stretch of the summary body; `sentence` is the index into the summary's sentences, or null for plain text. */
export type Piece = { text: string; sentence: number | null };

/**
 * The body cut at its sentences, so each can be selected. The body is shown exactly as stored: a sentence the
 * body does not contain word for word stays plain text. With no sentence found at all, the kept sentences are
 * shown in order instead.
 */
export function pieces(body: string, sentences: SummarySentence[]): Piece[] {
  const kept = sentences.map((s, index) => ({ text: s.text.trim(), index, removed: isRemoved(s) })).filter((s) => !s.removed && s.text);
  const out: Piece[] = [];
  let cursor = 0;
  let found = 0;
  for (const sentence of kept) {
    const at = body.indexOf(sentence.text, cursor);
    if (at < 0) continue;
    if (at > cursor) out.push({ text: body.slice(cursor, at), sentence: null });
    out.push({ text: sentence.text, sentence: sentence.index });
    cursor = at + sentence.text.length;
    found += 1;
  }
  if (kept.length === 0) return [{ text: body, sentence: null }];
  if (found === 0) return kept.flatMap((s, i) => [...(i ? [{ text: " ", sentence: null }] : []), { text: s.text, sentence: s.index }]);
  if (cursor < body.length) out.push({ text: body.slice(cursor), sentence: null });
  return out;
}

export type Confidence = { score: number; level: "high" | "medium" | "low"; reasons: string[] };

/** The confidence (0..100) with its level; the level falls back to the pipeline's thresholds (85 / 65). */
export function confidenceOf(summary: Summary | null | undefined): Confidence | null {
  const value = summary?.confidence;
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const score = Math.round(Math.min(100, Math.max(0, value)));
  const given = summary?.confidence_level;
  const level = given === "high" || given === "medium" || given === "low" ? given : score >= 85 ? "high" : score >= 65 ? "medium" : "low";
  const reasons = Array.isArray(summary?.confidence_reasons) ? summary.confidence_reasons.filter((r) => typeof r === "string") : [];
  return { score, level, reasons };
}
