/**
 * 鼠标朝向：宠物始终面朝光标所在的那一侧。
 *
 * 朝向是 CSS 镜像（`data-facing` → `scaleX(-1)`），所以换边只是翻一下，不打断当前动画。
 *
 * 两条规则：
 * 1. **光标在哪边就朝哪边**：宠物盒中心的左右。
 * 2. **带迟滞**：光标要越过中心一定距离才换边，否则在正中间来回移动会让宠物抽搐。
 *
 * 与随机转身的关系：随机链会定期播 turn 动画，播完翻转朝向。
 * 鼠标驱动时随机转身不该跟它对着干——turn 播完要转到**光标那一侧**，而不是对调。
 *
 * @module dsh-pet/src/client/pet/card/mouse-facing
 */

/** 朝向：left = 镜像（面朝左），right = 原样（面朝右）。 */
export type PointerSide = 'left' | 'right';

/** 换边所需的最小越界距离（px）：光标离中心这么近以内不算越边。 */
export const POINTER_HYSTERESIS_PX = 12;

/** 判定入参。 */
export interface SideInput {
  /** 宠物盒中心的视口 x。 */
  petCenterX: number;
  /** 光标的视口 x。 */
  pointerX: number;
  /** 当前朝向（迟滞带内保持它）。 */
  current: PointerSide;
  /** 迟滞距离（px）。 */
  hysteresis: number;
}

/**
 * 光标在宠物哪一侧。
 *
 * @param input - 判定入参。
 * @returns 该保持的朝向。
 */
export function sideTowardPointer(input: SideInput): PointerSide {
  const delta = input.pointerX - input.petCenterX;
  if (delta < -input.hysteresis) return 'left';
  if (delta > input.hysteresis) return 'right';
  return input.current;
}
