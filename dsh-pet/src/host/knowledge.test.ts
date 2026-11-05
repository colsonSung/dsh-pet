/**
 * 宠物「知道的事」的解析与降级（纯函数部分）。
 *
 * 四个来源各自有各自的落盘格式；这里只测「怎么从一份数据里挑出该给模型看的那几行」，
 * 以及「数据没了/变形了不能炸」。
 *
 * @module dsh-pet/src/host/knowledge
 */
import { deepStrictEqual, strictEqual } from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import {
  collectKnowledge,
  firstLine,
  memorySection,
  minutesSection,
  momentsSection,
  pmoSection,
  renderKnowledge,
  shortDate,
} from './knowledge.ts';

test('记忆：取领域标题与摘要', () => {
  const doc = {
    knowledge: {
      domains: [
        { title: 'English Reader 发布', summary: '已完成 v1.3.0 发布。' },
        { title: '本地化', summary: '欧洲商户自助进件还有缺口。' },
      ],
    },
  };
  const section = memorySection(doc, 5);
  strictEqual(section?.title, '记忆');
  deepStrictEqual(section?.lines, [
    'English Reader 发布：已完成 v1.3.0 发布。',
    '本地化：欧洲商户自助进件还有缺口。',
  ]);
});

test('记忆：超过上限只取前几条', () => {
  const doc = {
    knowledge: {
      domains: Array.from({ length: 10 }, (_, i) => ({ title: 'D' + i, summary: 's' + i })),
    },
  };
  strictEqual(memorySection(doc, 3)?.lines.length, 3);
});

test('记忆：数据缺失或没有领域时不产生这一段', () => {
  strictEqual(memorySection(undefined, 5), undefined);
  strictEqual(memorySection({}, 5), undefined);
  strictEqual(memorySection({ knowledge: {} }, 5), undefined);
  strictEqual(memorySection({ knowledge: { domains: [] } }, 5), undefined);
});

test('随手记：删掉的排除、钉住的排前面、其余按更新时间倒序', () => {
  const doc = {
    notes: [
      { id: 'a', content: '旧的', updatedAt: '2026-11-01T10:00:00Z' },
      { id: 'b', content: '新的\n第二行', updatedAt: '2026-11-04T10:00:00Z' },
      { id: 'c', content: '钉住的', updatedAt: '2026-10-01T10:00:00Z', pinned: true },
      { id: 'd', content: '删了的', updatedAt: '2026-11-05T10:00:00Z', deletedAt: '2026-11-05T11:00:00Z' },
    ],
  };
  const section = momentsSection(doc, 5);
  strictEqual(section?.title, '随手记');
  // 钉住的排最前，其余按更新时间倒序；上限 5 > 有效条数 3，所以三条都在。
  deepStrictEqual(section?.lines, ['10-01 钉住的', '11-04 新的', '11-01 旧的']);
});

test('随手记：时间是毫秒时间戳也能读（这些插件就是这么写的）', () => {
  const doc = {
    notes: [
      { id: 'a', content: '毫秒时间的笔记', updatedAt: 1793363621361 },
      { id: 'b', content: '更早的', updatedAt: 1793257857691 },
    ],
  };
  const section = momentsSection(doc, 5);
  strictEqual(section?.lines.length, 2);
  // 标签由时间戳算出来，不写死日期：写死会在时区或样本变化时变成假失败。
  const expected = shortDate(1793363621361);
  strictEqual(section?.lines[0]?.startsWith(expected + ' '), true);
});

test('随手记：时间读不出来的那条不出现，但别的照常', () => {
  const doc = { notes: [{ content: '没有时间', updatedAt: 'not a date' }, { content: '有时间的', updatedAt: 1793363621361 }] };
  const section = momentsSection(doc, 5);
  strictEqual(section?.lines.length, 1);
  strictEqual(section?.lines[0]?.includes('有时间的'), true);
});

test('随手记：没有可用笔记时不产生这一段', () => {
  strictEqual(momentsSection({ notes: [] }, 5), undefined);
  strictEqual(momentsSection({ notes: [{ content: '', updatedAt: '2026-11-01' }] }, 5), undefined);
});

test('需求与项目：按人给出焦点摘要，并附未完成任务数', () => {
  const doc = {
    personFocus: {
      '宋博-Ethan|weekly': { at: 200, lines: ['实质进展：本周完成 5 条需求。'] },
      'Leo Chen|weekly': { at: 100, lines: ['实质进展：对账专项在评审。'] },
    },
  };
  const effort = {
    total: 3,
    // PMO 的状态是大写下划线风格：CREATED / IN_PROGRESS / COMPLETED / CANCELLED
    subtasks: [{ status: 'CREATED' }, { status: 'COMPLETED' }, { status: 'IN_PROGRESS' }],
  };
  const section = pmoSection(doc, effort, 5);
  strictEqual(section?.title, '需求与项目');
  deepStrictEqual(section?.lines, [
    '宋博-Ethan：实质进展：本周完成 5 条需求。',
    'Leo Chen：实质进展：对账专项在评审。',
    '任务索引：共 3 条，其中未完成 2 条。',
  ]);
});

test('需求与项目：没有焦点也没有索引时不产生这一段', () => {
  strictEqual(pmoSection(undefined, undefined, 5), undefined);
  strictEqual(pmoSection({ personFocus: {} }, { total: 0, subtasks: [] }, 5), undefined);
});

test('会议纪要：目录不存在或为空时不产生这一段', async () => {
  const missing = join(tmpdir(), 'dsh-pet-no-such-minutes-' + Date.now());
  strictEqual(await minutesSection(missing, 5), undefined);
  const empty = await mkdtemp(join(tmpdir(), 'dsh-pet-empty-minutes-'));
  strictEqual(await minutesSection(empty, 5), undefined);
});

test('会议纪要：取最近的几场', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'dsh-pet-minutes-'));
  await writeFile(join(dir, 'a.json'), JSON.stringify({ title: '需求评审' }), 'utf8');
  await writeFile(join(dir, 'b.json'), JSON.stringify({ title: '周会' }), 'utf8');
  const section = await minutesSection(dir, 5);
  strictEqual(section?.title, '会议纪要');
  strictEqual(section?.lines.length, 2);
});

test('渲染：没有段落时是空串，有段落时给出标题与每条事实', () => {
  strictEqual(renderKnowledge([]), '');
  strictEqual(renderKnowledge([{ title: '空', lines: [] }]), '');
  const text = renderKnowledge([{ title: '记忆', lines: ['A', 'B'] }]);
  strictEqual(text.includes('【你掌握的情况】'), true);
  strictEqual(text.includes('· 记忆'), true);
  strictEqual(text.includes('  - A'), true);
});

test('日期：认得时间戳与 ISO 串，认不出就空串', () => {
  strictEqual(shortDate('2026-11-04T10:00:00Z'), '11-04');
  strictEqual(shortDate('2026-11-04'), '11-04');
  strictEqual(shortDate('not a date'), '');
  strictEqual(shortDate(undefined), '');
});

test('第一行：取首个非空行并截断', () => {
  strictEqual(firstLine('\n\n  正文  \n第二行'), '正文');
  strictEqual(firstLine('x'.repeat(200), 20).length, 20);
  strictEqual(firstLine(undefined), '');
});

test('汇总：四个来源里缺哪个都只是少一段', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'dsh-pet-knowledge-'));
  await mkdir(join(dir, 'memory'), { recursive: true });
  await writeFile(
    join(dir, 'memory', 'knowledge.json'),
    JSON.stringify({ knowledge: { domains: [{ title: 'T', summary: 'S' }] } }),
    'utf8',
  );
  const sections = await collectKnowledge({
    profileDir: dir,
    minutesDir: join(dir, 'no-minutes'),
    limit: 5,
  });
  strictEqual(sections.length, 1);
  strictEqual(sections[0]?.title, '记忆');
});
