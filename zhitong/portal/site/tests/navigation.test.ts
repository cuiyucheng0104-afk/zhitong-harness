import { describe, expect, it, vi } from 'vitest';
import { onTabKeydown } from '../src/lib/navigation';

describe('页签键盘操作', () => {
  it('方向键和 Home/End 将焦点与选择同步，末尾可循环', () => {
    const list = document.createElement('div');
    list.innerHTML =
      '<button role="tab">核对</button><button role="tab">投控</button><button role="tab">CAD</button>';
    document.body.append(list);
    const buttons = [...list.querySelectorAll('button')];
    const choose = vi.fn();
    list.addEventListener('keydown', onTabKeydown);
    list.addEventListener('click', choose);
    buttons[0]!.focus();
    buttons[0]!.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'End', bubbles: true, cancelable: true }),
    );
    expect(document.activeElement).toBe(buttons[2]);
    buttons[2]!.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }),
    );
    expect(document.activeElement).toBe(buttons[0]);
    expect(choose).toHaveBeenCalledTimes(2);
    list.remove();
  });
});
