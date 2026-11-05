/**
 * 宠物知道的「你的事」（宿主半侧）。
 *
 * 这台机器上还有别的插件在替你记事：dsh-memory（记忆）、moments-notes（随手记）、
 * ai-voice-minutes（会议纪要）、onerway-pmo（需求与项目）。它们各自在自己的目录里
 * 存数据，插件本身没有对外的读接口。这里按各自的落盘格式各取一小段事实，汇总成
 * 一段可以直接进提示词的文本——宠物因此能就你手上的事接话，而不只是说天气。
 *
 * 三条边界：
 * - 只读不改：这里没有任何写操作；
 * - 缺数据不报错：某个插件没装、文件不存在、格式变了，都只是那一段不出现；
 * - 长度有上限：提示词是给模型看的上下文，不是数据导出。
 *
 * @module dsh-pet/src/host/knowledge
 */
import { readFile, readdir, stat } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';

/** 一段事实：标题（模型的分组依据）与若干行（每行一个可引用的事实）。 */
export interface KnowledgeSection {
  /** 分组标题，如「记忆」「随手记」。 */
  title: string;
  /** 每行一个事实；空数组 = 这一段没有内容。 */
  lines: string[];
}

/** 收集的入参：路径与条数上限。 */
export interface KnowledgeOptions {
  /** DSH profile 目录：记忆、随手记、PMO 都在它下面。 */
  profileDir: string;
  /** 会议纪要目录（默认 ~/.ai-minutes/meetings）。 */
  minutesDir: string;
  /** 每个来源最多取几条。 */
  limit: number;
}

/** 默认的会议纪要目录（ai-voice-minutes 的落盘位置）。 */
export const DEFAULT_MINUTES_DIR = join(homedir(), '.ai-minutes', 'meetings');

/** 每段的事实条数上限（再高也只是把提示词撑长，不会让模型更懂你）。 */
export const KNOWLEDGE_LIMIT = 5;

/** 把一个时间戳压成「11-04」这样的短标签；认不出就返回空串。 */
export function shortDate(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? '' : pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }
  if (typeof value === 'string' && value !== '') {
    const d = new Date(value);
    if (!Number.isNaN(d.getTime())) return pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
    if (m) return m[2] + '-' + m[3];
  }
  return '';
}

/** 两位补零。 */
function pad(n: number): string {
  return n < 10 ? '0' + n : String(n);
}

/** 一段文字的第一行，压到给定长度。 */
export function firstLine(text: unknown, max = 120): string {
  if (typeof text !== 'string') return '';
  const line = text.split(/\r?\n/).find((l) => l.trim() !== '')?.trim() ?? '';
  return line.length > max ? line.slice(0, max - 1) + '…' : line;
}

/** 任意取值：对象取键、数组取元素、其余原样。 */
function pick(source: unknown, key: string): unknown {
  if (source && typeof source === 'object' && !Array.isArray(source)) {
    return (source as Record<string, unknown>)[key];
  }
  return undefined;
}

/** 取数组；不是数组就当没有。 */
function list(source: unknown): unknown[] {
  return Array.isArray(source) ? source : [];
}

/**
 * 各种时间写法统一成毫秒时间戳。
 *
 * 不能直接 `new Date(String(v))`：这些插件写的是毫秒数，字符串化后会被当成年份解析而失败。
 */
function toMillis(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value !== '') {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) return parsed.getTime();
  }
  return 0;
}

/** 任务索引里算「已结束」的状态（PMO 用的是大写下划线风格）。 */
const CLOSED_STATUSES = new Set(['completed', 'done', 'closed', 'cancelled', 'canceled']);

/**
 * 记忆（dsh-memory）：它把事实整理成「领域」——每个领域有标题、摘要和若干结论。
 * 这些结论是现成的、已经成文的事实，比原始日志更适合直接喂给模型。
 */
export function memorySection(doc: unknown, limit: number): KnowledgeSection | undefined {
  const knowledge = pick(doc, 'knowledge');
  const domains = list(pick(knowledge, 'domains'));
  const lines: string[] = [];
  for (const domain of domains) {
    const title = firstLine(pick(domain, 'title'), 40);
    const summary = firstLine(pick(domain, 'summary'), 140);
    if (title === '' && summary === '') continue;
    lines.push(title === '' ? summary : title + '：' + summary);
    if (lines.length >= limit) break;
  }
  if (lines.length === 0) return undefined;
  return { title: '记忆', lines };
}

/**
 * 随手记（moments-notes）：用户随手写下的备忘，按更新时间倒序。
 * 钉住的（pinned）排在前面——那是用户明确说要留着的。
 */
export function momentsSection(doc: unknown, limit: number): KnowledgeSection | undefined {
  const notes = list(pick(doc, 'notes')).filter((n) => !pick(n, 'deletedAt'));
  const dated = notes
    .map((n) => ({
      note: n,
      at: toMillis(pick(n, 'updatedAt') ?? pick(n, 'createdAt')),
      pinned: pick(n, 'pinned') === true,
    }))
    .filter((n) => n.at > 0)
    .sort((a, b) => (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || b.at - a.at);
  const lines: string[] = [];
  for (const { note, at } of dated) {
    const body = firstLine(pick(note, 'content'), 120);
    if (body === '') continue;
    const when = shortDate(at);
    lines.push(when === '' ? body : when + ' ' + body);
    if (lines.length >= limit) break;
  }
  if (lines.length === 0) return undefined;
  return { title: '随手记', lines };
}

/**
 * 需求与项目（onerway-pmo）：它按人算出「本周实质进展 / 投入 / 产出」的焦点摘要，
 * 另有全量任务的工作量索引。前者是成文的结论，后者用来回答「我手上还有多少事」。
 */
export function pmoSection(doc: unknown, effort: unknown, limit: number): KnowledgeSection | undefined {
  const lines: string[] = [];
  const focus = pick(doc, 'personFocus');
  if (focus && typeof focus === 'object' && !Array.isArray(focus)) {
    const entries = Object.entries(focus as Record<string, unknown>);
    entries.sort((a, b) => Number(pick(b[1], 'at') ?? 0) - Number(pick(a[1], 'at') ?? 0));
    for (const [key, value] of entries) {
      const person = key.split('|')[0];
      const focusLines = list(pick(value, 'lines'));
      const first = firstLine(focusLines[0], 140);
      if (first === '') continue;
      lines.push(person + '：' + first);
      if (lines.length >= limit) break;
    }
  }
  const total = pick(effort, 'total');
  const subtasks = list(pick(effort, 'subtasks'));
  if (typeof total === 'number' && Number.isFinite(total) && total > 0) {
    const open = subtasks.filter(
      (s) => !CLOSED_STATUSES.has(String(pick(s, 'status') ?? '').toLowerCase()),
    ).length;
    lines.push('任务索引：共 ' + total + ' 条，其中未完成 ' + open + ' 条。');
  }
  if (lines.length === 0) return undefined;
  return { title: '需求与项目', lines };
}

/**
 * 会议纪要（ai-voice-minutes）：每次会议一个文件，取最近的几场。
 * 目录为空或没装过这个插件时没有这一段。
 */
export async function minutesSection(dir: string, limit: number): Promise<KnowledgeSection | undefined> {
  let names: string[];
  try {
    names = await readdir(dir);
  } catch {
    return undefined;
  }
  const files = names.filter((n) => n.endsWith('.json'));
  if (files.length === 0) return undefined;
  const dated = await Promise.all(
    files.map(async (name) => {
      try {
        const info = await stat(join(dir, name));
        return { name, at: info.mtimeMs };
      } catch {
        return { name, at: 0 };
      }
    }),
  );
  dated.sort((a, b) => b.at - a.at);
  const lines: string[] = [];
  for (const { name, at } of dated) {
    if (lines.length >= limit) break;
    try {
      const doc = JSON.parse(await readFile(join(dir, name), 'utf8'));
      const title = firstLine(pick(doc, 'title') ?? pick(doc, 'name') ?? name.replace(/\.json$/, ''), 60);
      const when = shortDate(at);
      lines.push(when === '' ? title : when + ' ' + title);
    } catch {
      // 一个坏文件不该让整段消失：跳过它，继续收下一场。
    }
  }
  if (lines.length === 0) return undefined;
  return { title: '会议纪要', lines };
}

/**
 * 汇总四段事实。每一段独立取：某段失败只是那段没有，不影响别的。
 */
export async function collectKnowledge(options: KnowledgeOptions): Promise<KnowledgeSection[]> {
  const limit = Math.max(1, Math.floor(options.limit));
  const sections: KnowledgeSection[] = [];
  const read = async (path: string): Promise<unknown> => {
    try {
      return JSON.parse(await readFile(path, 'utf8'));
    } catch {
      return undefined;
    }
  };
  const memory = memorySection(await read(join(options.profileDir, 'memory', 'knowledge.json')), limit);
  if (memory) sections.push(memory);
  const moments = momentsSection(await read(join(options.profileDir, 'moments-notes', 'notes.json')), limit);
  if (moments) sections.push(moments);
  const minutes = await minutesSection(options.minutesDir, limit);
  if (minutes) sections.push(minutes);
  const pmo = pmoSection(
    await read(join(options.profileDir, 'onerway-pmo', 'analyses.json')),
    await read(join(options.profileDir, 'onerway-pmo', 'effort-index.json')),
    limit,
  );
  if (pmo) sections.push(pmo);
  return sections;
}

/**
 * 把事实汇总渲染成提示词里的一段。
 *
 * 写成「你掌握的情况」而不是「资料」：这几句是宠物可以拿来接话的事实，
 * 不是要它复述的文档。
 */
export function renderKnowledge(sections: KnowledgeSection[]): string {
  const usable = sections.filter((s) => s.lines.length > 0);
  if (usable.length === 0) return '';
  const lines = ['【你掌握的情况】'];
  for (const section of usable) {
    lines.push('· ' + section.title);
    for (const line of section.lines) lines.push('  - ' + line);
  }
  lines.push('这些是你自己那摊事的事实。需要时直接引用其中具体的一条，不要笼统地说「你最近很忙」。');
  return lines.join('\n');
}
