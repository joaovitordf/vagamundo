import { Injectable, signal } from '@angular/core';

export type ToastKind = 'success' | 'info' | 'warning' | 'error';

export interface ToastMessage {
  id: number;
  kind: ToastKind;
  text: string;
}

@Injectable({
  providedIn: 'root',
})
export class ToastService {
  private nextId = 1;
  private readonly timers = new Map<number, ReturnType<typeof setTimeout>>();

  readonly toasts = signal<ToastMessage[]>([]);

  show(text: string, kind: ToastKind = 'info', durationMs = 4500): number {
    const clean = (text || '').trim();
    if (!clean) return -1;
    const id = this.nextId++;
    this.toasts.update((list) => [...list.slice(-3), { id, kind, text: clean }]);
    if (durationMs > 0) {
      const timer = setTimeout(() => this.dismiss(id), durationMs);
      this.timers.set(id, timer);
    }
    return id;
  }

  success(text: string, durationMs = 4000): number {
    return this.show(text, 'success', durationMs);
  }

  info(text: string, durationMs = 4000): number {
    return this.show(text, 'info', durationMs);
  }

  warning(text: string, durationMs = 5000): number {
    return this.show(text, 'warning', durationMs);
  }

  error(text: string, durationMs = 6500): number {
    return this.show(text, 'error', durationMs);
  }

  dismiss(id: number): void {
    const timer = this.timers.get(id);
    if (timer) {
      clearTimeout(timer);
      this.timers.delete(id);
    }
    this.toasts.update((list) => list.filter((t) => t.id !== id));
  }
}
