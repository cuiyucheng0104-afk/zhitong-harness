/**
 * 锚点 id 函数（06 章 §2.4）：构建期（清单、markdown-it-anchor）与运行时共用，锚点 id 只由这里生成。
 *
 * 规则：去掉首尾空白；删除除字母、数字（含中文）、`-`、空格之外的字符；空格换成 `-`；英文转小写。
 * 同页重名依次加 `-2`、`-3`（由 `createSlugger` 处理）。
 * 例：「校验安装包」→ `校验安装包`；「Windows：SmartScreen 拦截」→ `windowssmartscreen-拦截`。
 */

/**
 * 由标题文字生成锚点 id（不处理重名）。
 * @param text - 标题纯文本。
 * @returns 锚点 id。
 */
export function slugify(text: string): string {
  return text
    .trim()
    .replace(/[^\p{L}\p{N}\- ]/gu, '')
    .replace(/ /g, '-')
    .toLowerCase();
}

/**
 * 创建一页内的锚点生成器：同页重名依次加 `-2`、`-3`。
 * @returns `(text) => id`。
 */
export function createSlugger(): (text: string) => string {
  const seen = new Map<string, number>();
  return (text: string) => {
    const base = slugify(text);
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    return n === 1 ? base : `${base}-${n}`;
  };
}
