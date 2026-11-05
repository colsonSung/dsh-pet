/**
 * 鼠标朝向的判定（纯函数契约）：光标在哪边就朝哪边，带迟滞。
 *
 * 跑法：node --experimental-strip-types --test src/client/pet/card/mouse-facing.test.ts
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { POINTER_HYSTERESIS_PX, sideTowardPointer } from './mouse-facing.ts';

describe('鼠标朝向', () => {
  test('光标在左边 → 面朝左', () => {
    assert.equal(
      sideTowardPointer({ current: 'right', hysteresis: POINTER_HYSTERESIS_PX, petCenterX: 500, pointerX: 100 }),
      'left',
    );
  });

  test('光标在右边 → 面朝右', () => {
    assert.equal(
      sideTowardPointer({ current: 'left', hysteresis: POINTER_HYSTERESIS_PX, petCenterX: 500, pointerX: 900 }),
      'right',
    );
  });

  test('光标越过中心但还在迟滞带内 → 保持当前（不抽搐）', () => {
    assert.equal(
      sideTowardPointer({ current: 'left', hysteresis: POINTER_HYSTERESIS_PX, petCenterX: 500, pointerX: 505 }),
      'left',
    );
    assert.equal(
      sideTowardPointer({ current: 'right', hysteresis: POINTER_HYSTERESIS_PX, petCenterX: 500, pointerX: 495 }),
      'right',
    );
  });

  test('光标刚好在中心上 → 保持当前', () => {
    assert.equal(
      sideTowardPointer({ current: 'left', hysteresis: POINTER_HYSTERESIS_PX, petCenterX: 500, pointerX: 500 }),
      'left',
    );
  });

  test('越过迟滞带 → 换边', () => {
    const h = POINTER_HYSTERESIS_PX;
    assert.equal(
      sideTowardPointer({ current: 'left', hysteresis: h, petCenterX: 500, pointerX: 500 + h + 1 }),
      'right',
    );
    assert.equal(
      sideTowardPointer({ current: 'right', hysteresis: h, petCenterX: 500, pointerX: 500 - h - 1 }),
      'left',
    );
  });
});
