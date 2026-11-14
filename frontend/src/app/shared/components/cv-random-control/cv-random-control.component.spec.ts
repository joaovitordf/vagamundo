import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { CvRandomControlComponent } from './cv-random-control.component';

describe('CvRandomControlComponent', () => {
  let fixture: ComponentFixture<CvRandomControlComponent>;
  let component: CvRandomControlComponent;
  let router: Router;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CvRandomControlComponent],
      providers: [provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(CvRandomControlComponent);
    component = fixture.componentInstance;
    router = TestBed.inject(Router);
  });

  it('emits pickRandom when clicking Sortear área CV', () => {
    let picked = 0;
    component.pickRandom.subscribe(() => {
      picked += 1;
    });
    component.areasCount = 4;
    component.source = 'profile';
    fixture.detectChanges();

    const btn = fixture.nativeElement.querySelector('.btn-random-cv') as HTMLButtonElement;
    btn.click();

    expect(picked).toBe(1);
    expect(component.infoOpen()).toBeFalse();
  });

  it('toggles info popover with explanation and navigates to Meu perfil with focus query param', () => {
    spyOn(router, 'navigate').and.resolveTo(true);
    component.areasCount = 5;
    component.source = 'profile';
    fixture.detectChanges();

    const infoBtn = fixture.nativeElement.querySelector('.btn-random-info') as HTMLButtonElement;
    infoBtn.click();
    fixture.detectChanges();

    const popover = fixture.nativeElement.querySelector('.cv-info-popover') as HTMLElement;
    expect(popover).not.toBeNull();
    expect(popover.textContent).toContain('Meu perfil');
    expect(popover.textContent).toContain('5 palavra(s) configurada(s) no Meu perfil');

    const editBtn = fixture.nativeElement.querySelector('.cv-info-link-btn') as HTMLButtonElement;
    editBtn.click();
    expect(router.navigate).toHaveBeenCalledWith(['/meu-perfil'], {
      queryParams: { foco: 'palavras_chave_sorteio' },
    });
    expect(component.infoOpen()).toBeFalse();
  });

  it('closes popover on Escape key press', () => {
    fixture.detectChanges();
    component.infoOpen.set(true);
    fixture.detectChanges();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    fixture.detectChanges();

    expect(component.infoOpen()).toBeFalse();
  });
});
