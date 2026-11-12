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
            screening: { score: 80 },
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
    expect(cards[1].querySelector('.vc-badge-fit--low')?.textContent).toContain('35/100');
    expect(cards[1].querySelector('.vc-badge-fit--low')?.textContent).toContain('Weak Fit');
    expect(cards[1].textContent).toContain('São Paulo, Brazil');
    expect(cards[1].querySelector('.link-external')?.getAttribute('href')).toBe('https://example.com/2');

    expect(cards[2].querySelector('.job-card__title')?.textContent?.trim()).toBe('Fullstack Pleno');
    expect(cards[2].querySelector('.vc-badge-fit--high')?.textContent).toContain('80/100');
    expect(cards[2].querySelector('.vc-badge-fit--high')?.textContent).toContain('Alta Afinidade');
  });
});
