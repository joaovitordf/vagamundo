import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { ToastService } from './toast.service';

describe('ToastService', () => {
  let service: ToastService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(ToastService);
  });

  it('adds typed toasts, caps visible stack at 4, and dismisses by id', () => {
    const id1 = service.success('Salvo');
    const id2 = service.info('Atualizado');
    const id3 = service.warning('Atenção');
    const id4 = service.error('Falha');
    const id5 = service.show('Extra', 'info', 0);

    const visible = service.toasts();
    expect(visible.length).toBe(4);
    expect(visible.some(t => t.id === id1)).toBeFalse();
    expect(visible.map(t => t.id)).toEqual([id2, id3, id4, id5]);
    expect(visible[2].kind).toBe('error');

    service.dismiss(id4);
    expect(service.toasts().map(t => t.id)).toEqual([id2, id3, id5]);
  });

  it('auto-dismisses toast after durationMs expires', fakeAsync(() => {
    const id = service.success('Concluído', 2000);
    expect(service.toasts().some(t => t.id === id)).toBeTrue();

    tick(1999);
    expect(service.toasts().some(t => t.id === id)).toBeTrue();

    tick(1);
    expect(service.toasts().some(t => t.id === id)).toBeFalse();
  }));
});
