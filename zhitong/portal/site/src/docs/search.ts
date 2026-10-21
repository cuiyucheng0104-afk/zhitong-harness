/**
 * 站内搜索（06 章 §8.4–§8.5）：独立懒加载块。首次使用时 fetch 同源索引并在内存中建立倒排表，之后复用。
 *
 * - 规范化：NFKC、英文小写；整句比对时去掉空白与标点。
 * - 切分：连续汉字切成重叠二字组；连续字母数字（含 `_`）为一个词，查询词长度 ≥ 2 时按前缀匹配；查询只有一个汉字时用单字。
 * - 同义词：查询含同义词表中的词时，同组其它词替换后的查询按「或」参与匹配（取最高分）。
 * - 评分：小节至少命中查询词组的 70%；每个命中词：页标题 +8、小节标题 +4、正文 +1（同一词正文最多计 3 次）；
 *   规范化后的整句查询在小节标题或正文中原样出现再 +10。同分按清单顺序。
 * - 摘录：以第一个整句命中处（没有则第一个词命中处）为中心取前后各 40 字，首尾加「…」，命中区间合并后标记。
 */
import indexUrl from 'virtual:docs-search-index';
import synonymGroups from './search-synonyms.json';

export interface SearchIndexData {
  v: 1;
  pages: { p: string; t: string; g: string }[];
  sections: { d: number; h: string; a: string; x: string }[];
}

/** 摘录片段：`mark` 为命中文字。 */
export interface ExcerptPart {
  text: string;
  mark: boolean;
}

export interface SearchResult {
  /** 页面路径，如 `/docs/install/`。 */
  path: string;
  /** 带锚点的跳转地址。 */
  href: string;
  pageTitle: string;
  heading: string;
  anchor: string;
  excerpt: ExcerptPart[];
  score: number;
}

const HAN = /\p{Script=Han}/u;
const WORD = /[\p{L}\p{N}_]/u;

/** 规范化：NFKC + 小写。 */
export const normalize = (s: string) => s.normalize('NFKC').toLowerCase();
/** 去掉空白与标点（整句比对用）。 */
export const compact = (s: string) => normalize(s).replace(/[^\p{L}\p{N}_]/gu, '');

/**
 * 切分为检索词。
 * @param text - 文本（已规范化或未规范化均可）。
 * @param query - 是否为查询（查询只有一个汉字时用单字）。
 * @returns 词列表（汉字二字组带前缀 `h:`，字母数字词带前缀 `w:`）。
 */
export function tokenize(text: string, query = false): string[] {
  const s = normalize(text);
  const out: string[] = [];
  let han = '';
  let word = '';
  const flushHan = () => {
    if (han.length === 1 && query) out.push(`u:${han}`);
    for (let i = 0; i + 1 < han.length; i++) out.push(`h:${han.slice(i, i + 2)}`);
    han = '';
  };
  const flushWord = () => {
    if (word) out.push(`w:${word}`);
    word = '';
  };
  for (const ch of s) {
    if (HAN.test(ch)) {
      flushWord();
      han += ch;
    } else if (WORD.test(ch)) {
      flushHan();
      word += ch;
    } else {
      flushHan();
      flushWord();
    }
  }
  flushHan();
  flushWord();
  return out;
}

type Postings = Map<string, Map<number, number>>;

function addAll(map: Postings, terms: string[], section: number) {
  for (const t of terms) {
    let p = map.get(t);
    if (!p) map.set(t, (p = new Map()));
    p.set(section, (p.get(section) ?? 0) + 1);
  }
}

/** 一份建好的索引（三张表：页标题、小节标题、正文）。 */
export interface Searcher {
  data: SearchIndexData;
  search(query: string): SearchResult[];
}

/**
 * 由索引数据建立检索器。
 * @param data - 索引 JSON。
 * @returns 检索器。
 */
export function createSearcher(data: SearchIndexData): Searcher {
  const title: Postings = new Map();
  const heading: Postings = new Map();
  const body: Postings = new Map();
  const texts = data.sections.map((s) => ({ h: normalize(s.h), x: normalize(s.x), t: normalize(data.pages[s.d].t) }));
  data.sections.forEach((s, i) => {
    addAll(title, tokenize(data.pages[s.d].t), i);
    addAll(heading, tokenize(s.h), i);
    addAll(body, tokenize(s.x), i);
  });
  const vocab = [...new Set([...title.keys(), ...heading.keys(), ...body.keys()])].filter((k) => k.startsWith('w:'));

  /** 一个查询词对应的索引词（字母数字词长度 ≥ 2 时前缀匹配）。 */
  const expand = (term: string): string[] => {
    if (!term.startsWith('w:') || term.length < 4) return [term];
    return vocab.filter((v) => v.startsWith(term));
  };

  const hitsIn = (map: Postings, keys: string[], section: number) => {
    let n = 0;
    for (const k of keys) n += map.get(k)?.get(section) ?? 0;
    return n;
  };

  function scoreVariant(q: string, scores: Map<number, { score: number; q: string }>) {
    const terms = [...new Set(tokenize(q, true))];
    if (!terms.length) return;
    const phrase = compact(q);
    const single = terms.length === 1 && terms[0].startsWith('u:') ? terms[0].slice(2) : null;
    const keys = terms.map(expand);
    const candidates = new Set<number>();
    if (single) texts.forEach((t, i) => (t.t + t.h + t.x).includes(single) && candidates.add(i));
    else for (const ks of keys) for (const k of ks) for (const map of [title, heading, body]) map.get(k)?.forEach((_, i) => candidates.add(i));
    for (const i of candidates) {
      let matched = 0;
      let score = 0;
      if (single) {
        matched = 1;
        if (texts[i].t.includes(single)) score += 8;
        if (texts[i].h.includes(single)) score += 4;
        score += Math.min(3, texts[i].x.split(single).length - 1);
      } else
        keys.forEach((ks) => {
          const t = hitsIn(title, ks, i);
          const h = hitsIn(heading, ks, i);
          const b = hitsIn(body, ks, i);
          if (t || h || b) matched++;
          score += (t ? 8 : 0) + (h ? 4 : 0) + Math.min(3, b);
        });
      if (matched / keys.length < 0.7) continue;
      if (phrase.length > 1 && (compact(texts[i].h).includes(phrase) || compact(texts[i].x).includes(phrase))) score += 10;
      const prev = scores.get(i);
      if (!prev || score > prev.score) scores.set(i, { score, q });
    }
  }

  function variants(query: string): string[] {
    const q = normalize(query);
    const out = new Set([q]);
    for (const group of synonymGroups as string[][]) {
      const words = group.map(normalize);
      for (const w of words) {
        // 英文词按整词匹配（避免 task 里的 sk 被当成同义词），汉字词按子串。
        const ascii = /^[a-z0-9_.]+$/.test(w);
        const re = ascii
          ? new RegExp(`(?<![a-z0-9_])${w.replace(/\./g, '\\.')}(?![a-z0-9_])`, 'g')
          : new RegExp(w, 'g');
        if (!q.match(re)) continue;
        for (const other of words) if (other !== w) out.add(q.replace(re, other));
      }
    }
    return [...out];
  }

  function excerpt(text: string, q: string): ExcerptPart[] {
    // 逐字规范化并记下每个规范化字符对应的原文位置（NFKC 可能改变长度，如「…」→「...」）。
    let lower = '';
    const origin: number[] = [];
    let o = 0;
    for (const ch of text) {
      const n = normalize(ch);
      for (let k = 0; k < n.length; k++) origin.push(o);
      lower += n;
      o += ch.length;
    }
    origin.push(text.length);
    const phrase = normalize(q).trim();
    const ranges: [number, number][] = [];
    const find = (needle: string) => {
      if (!needle) return;
      let from = 0;
      for (;;) {
        const at = lower.indexOf(needle, from);
        if (at < 0) break;
        ranges.push([at, at + needle.length]);
        from = at + needle.length;
      }
    };
    const phraseAt = phrase.length > 1 ? lower.indexOf(phrase) : -1;
    if (phraseAt >= 0) find(phrase);
    for (const t of tokenize(q, true)) find(t.slice(2));
    // 英文前缀命中：把整个词标出来（如 zt_not → zt_not_importable）。
    for (const r of ranges) while (r[1] < lower.length && /[a-z0-9_]/.test(lower[r[1]])) r[1]++;
    ranges.sort((a, b) => a[0] - b[0]);
    const merged: [number, number][] = [];
    for (const [a, b] of ranges) {
      const last = merged.at(-1);
      const s0 = origin[a];
      const e0 = origin[b];
      if (last && s0 <= last[1]) last[1] = Math.max(last[1], e0);
      else merged.push([s0, e0]);
    }
    const center = phraseAt >= 0 ? origin[phraseAt] : (merged[0]?.[0] ?? 0);
    const start = Math.max(0, center - 40);
    const end = Math.min(text.length, center + 40 + (phraseAt >= 0 ? phrase.length : 0));
    const parts: ExcerptPart[] = [];
    if (start > 0) parts.push({ text: '…', mark: false });
    let pos = start;
    for (const [a, b] of merged) {
      if (b <= start || a >= end) continue;
      const s1 = Math.max(a, pos);
      const e1 = Math.min(b, end);
      if (s1 > pos) parts.push({ text: text.slice(pos, s1), mark: false });
      if (e1 > s1) parts.push({ text: text.slice(s1, e1), mark: true });
      pos = Math.max(pos, e1);
    }
    if (pos < end) parts.push({ text: text.slice(pos, end), mark: false });
    if (end < text.length) parts.push({ text: '…', mark: false });
    return parts;
  }

  function search(query: string): SearchResult[] {
    if (!query.trim()) return [];
    const scores = new Map<number, { score: number; q: string }>();
    for (const v of variants(query)) scoreVariant(v, scores);
    const ranked = [...scores.entries()].sort((a, b) => b[1].score - a[1].score || a[0] - b[0]);
    // 按页分组（页的先后取其最高分小节），每页最多 3 个小节，总数最多 20 条。
    const pageOrder: number[] = [];
    const perPage = new Map<number, number[]>();
    for (const [i] of ranked) {
      const d = data.sections[i].d;
      if (!perPage.has(d)) {
        perPage.set(d, []);
        pageOrder.push(d);
      }
      const list = perPage.get(d)!;
      if (list.length < 3) list.push(i);
    }
    const out: SearchResult[] = [];
    for (const d of pageOrder)
      for (const i of perPage.get(d)!) {
        if (out.length >= 20) return out;
        const s = data.sections[i];
        const page = data.pages[s.d];
        const hit = scores.get(i)!;
        out.push({
          path: page.p,
          href: s.a ? `${page.p}#${s.a}` : page.p,
          pageTitle: page.t,
          heading: s.h,
          anchor: s.a,
          excerpt: excerpt(s.x || s.h, hit.q),
          score: hit.score,
        });
      }
    return out;
  }

  return { data, search };
}

let loading: Promise<Searcher> | undefined;

/**
 * 载入索引并建立检索器（只取一次）。失败时下次调用重试。
 * @returns 检索器。
 */
export function loadSearcher(): Promise<Searcher> {
  loading ??= fetch(indexUrl, { credentials: 'same-origin' })
    .then((r) => {
      if (!r.ok) throw new Error(`搜索索引 HTTP ${r.status}`);
      return r.json() as Promise<SearchIndexData>;
    })
    .then(createSearcher)
    .catch((e: unknown) => {
      loading = undefined;
      throw e;
    });
  return loading;
}
