import { ComponentFixture, TestBed } from '@angular/core/testing';
import { JobBadgesComponent } from './job-badges.component';
import { ScreeningResult } from '../../core/models/vaga.model';

describe('JobBadgesComponent', () => {
  let fixture: ComponentFixture<JobBadgesComponent>;
  let component: JobBadgesComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [JobBadgesComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(JobBadgesComponent);
    component = fixture.componentInstance;
  });

  it('does not render badge stack when no badge inputs are provided', () => {
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.vc-badge-stack')).toBeNull();
  });

  it('renders high/med/low fit classes using FIT_THRESHOLDS (75 / 60)', () => {
    component.score = 75;
    component.verdict = 'Strong Fit';
    fixture.detectChanges();

    let fit = fixture.nativeElement.querySelector('.vc-badge-fit') as HTMLElement;
    expect(fit.classList).toContain('vc-badge-fit--high');
    expect(fit.textContent).toContain('75/100');
    expect(fit.textContent).toContain('Strong Fit');

    component.score = 74;
    component.verdict = 'Moderate Fit';
    fixture.detectChanges();
    fit = fixture.nativeElement.querySelector('.vc-badge-fit') as HTMLElement;
    expect(fit.classList).toContain('vc-badge-fit--med');

    component.score = 60;
    fixture.detectChanges();
    fit = fixture.nativeElement.querySelector('.vc-badge-fit') as HTMLElement;
    expect(fit.classList).toContain('vc-badge-fit--med');

    component.score = 59;
    component.verdict = 'Weak Fit';
    fixture.detectChanges();
    fit = fixture.nativeElement.querySelector('.vc-badge-fit') as HTMLElement;
    expect(fit.classList).toContain('vc-badge-fit--low');
  });

  it('renders ai_model, subscores tooltip, auto-recruiter badge, and gate chips', () => {
    const screening: ScreeningResult = {
      score: 88,
      verdict: 'Strong Fit',
      ai_model: 'gpt-4o-mini',
      language_gate: 'FLAG',
      location_verdict: 'FAIL',
      subscores: {
        technical: 92,
        experience: 85,
        behavioral: 80,
        career: 90,
      },
    };

    component.screening = screening;
    component.autoPromoted = true;
    component.autoOrigin = 'recruiter';
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const autoBadge = el.querySelector('.badge-auto-promoted') as HTMLElement;
    expect(autoBadge).not.toBeNull();
    expect(autoBadge.textContent).toContain('Auto · Recrutador');

    const modelBadge = el.querySelector('.vc-badge-model') as HTMLElement;
    expect(modelBadge.textContent).toContain('gpt-4o-mini');

    const fitBadge = el.querySelector('.vc-badge-fit') as HTMLElement;
    expect(fitBadge.getAttribute('title')).toBe('Téc: 92 · Exp: 85 · Comp: 80 · Carr: 90');

    const gates = Array.from(el.querySelectorAll('.vc-badge-gate')) as HTMLElement[];
    expect(gates.length).toBe(2);
    expect(gates[0].textContent).toContain('Idioma: FLAG');
    expect(gates[0].classList).not.toContain('vc-badge-gate--fail');
    expect(gates[1].textContent).toContain('Local: FAIL');
    expect(gates[1].classList).toContain('vc-badge-gate--fail');
  });
});
