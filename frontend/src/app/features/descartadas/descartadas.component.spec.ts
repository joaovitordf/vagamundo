import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { DescartadasComponent } from './descartadas.component';

describe('DescartadasComponent', () => {
  let fixture: ComponentFixture<DescartadasComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DescartadasComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(DescartadasComponent);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.match(() => true);
  });

  it('renders all discarded job cards even when the first item has screening === null', () => {
    fixture.detectChanges();

    // Constructor of ApiService fires /api/token + refreshCounts (/api/saved, /api/applications, /api/discarded),
    // and DescartadasComponent.ngOnInit fires /api/discarded as well.
    for (const req of httpMock.match('/api/token')) {
      req.flush({ token: 'tok' });
    }
    for (const req of httpMock.match('/api/saved')) {
      req.flush({ saved: [] });
    }
    for (const req of httpMock.match('/api/applications')) {
      req.flush({ applications: [] });
    }

    const discardedReqs = httpMock.match('/api/discarded');
    expect(discardedReqs.length).toBeGreaterThan(0);
    for (const req of discardedReqs) {
      req.flush({
        discarded: [
          {
            title: 'Product Owner',
            company: 'Omega',
            portal: 'remotar-search',
            url: 'https://example.com/1',
            location: null,
            date: '2026-10-19',
            screening: null,
          },
          {
            title: 'Staff Frontend Software Engineer',
            company: 'Tractian',
            portal: 'linkedin-search',
            url: 'https://example.com/2',
            location: 'São Paulo, Brazil',
            date: '2026-11-09',
            screening: { score: 35, verdict: 'Weak Fit' },
          },
          {
            title: 'Fullstack Pleno',
            company: 'Acme',
            portal: 'freehire-search',
            url: 'https://example.com/3',
            location: 'Remoto',
            date: '2026-11-10',
            screening: { score: 80, ai_model: 'gemini-4-hydrogen-high' },
          },
        ],
      });
    }

    fixture.detectChanges();

    const cards = Array.from(
      fixture.nativeElement.querySelectorAll('.job-card')
    ) as HTMLElement[];
    expect(cards.length).toBe(3);

    expect(cards[0].querySelector('.job-card__title')?.textContent?.trim()).toBe('Product Owner');
    expect(cards[0].querySelector('.job-card__company')?.textContent).toContain('Omega');
    expect(cards[0].querySelector('.job-card__company')?.textContent).toContain('Remotar');
    expect(cards[0].textContent).toContain('2026-10-19');
    expect(cards[0].querySelector('.vc-badge-fit')).toBeNull();

    expect(cards[1].querySelector('.job-card__title')?.textContent?.trim()).toBe('Staff Frontend Software Engineer');
    expect(cards[1].querySelector('.job-card__company')?.textContent).toContain('Tractian');
    expect(cards[1].querySelector('app-portal-badge [data-portal="linkedin-search"] i.bi-linkedin')).not.toBeNull();
    expect(cards[1].querySelector('.vc-badge-fit--low')?.textContent).toContain('35/100');
    expect(cards[1].querySelector('.vc-badge-fit--low')?.textContent).toContain('Weak Fit');
    expect(cards[1].querySelector('.vc-badge-model')).toBeNull();
    expect(cards[1].textContent).toContain('São Paulo, Brazil');
    expect(cards[1].querySelector('.link-external')?.getAttribute('href')).toBe('https://example.com/2');

    expect(cards[2].querySelector('.job-card__title')?.textContent?.trim()).toBe('Fullstack Pleno');
    expect(cards[2].querySelector('.vc-badge-fit--high')?.textContent).toContain('80/100');
    expect(cards[2].querySelector('.vc-badge-fit--high')?.textContent).toContain('Alta Afinidade');
    expect(cards[2].querySelector('.vc-badge-model')?.textContent).toContain('gemini-4-hydrogen-high');
  });

  it('uses canonical 60 cutoff on fit badges and renders language/location gate chips', () => {
    fixture.detectChanges();
    for (const req of httpMock.match('/api/token')) {
      req.flush({ token: 'tok' });
    }
    for (const req of httpMock.match('/api/saved')) {
      req.flush({ saved: [] });
    }
    for (const req of httpMock.match('/api/applications')) {
      req.flush({ applications: [] });
    }
    for (const req of httpMock.match('/api/discarded')) {
      req.flush({
        discarded: [
          {
            title: 'Vaga 58',
            company: 'X',
            portal: 'gupy-search',
            url: 'https://example.com/d58',
            screening: { score: 58, verdict: 'Moderate Fit', language_gate: 'FAIL', language_note: 'Alemão C1' },
          },
          {
            title: 'Vaga 60',
            company: 'Y',
            portal: 'gupy-search',
            url: 'https://example.com/d60',
            screening: { score: 60, location_verdict: 'FLAG' },
          },
        ],
      });
    }
    fixture.detectChanges();

    const cards = Array.from(fixture.nativeElement.querySelectorAll('.job-card')) as HTMLElement[];
    expect(cards[0].querySelector('.vc-badge-fit--low')?.textContent).toContain('58/100');
    expect(cards[0].querySelector('.vc-badge-gate--fail')?.textContent).toContain('Idioma: FAIL');
    expect(cards[1].querySelector('.vc-badge-fit--med')?.textContent).toContain('60/100');
    expect(cards[1].querySelector('.vc-badge-fit--med')?.textContent).toContain('Média Afinidade');
    expect(cards[1].querySelector('.vc-badge-gate')?.textContent).toContain('Local: FLAG');
  });
});
