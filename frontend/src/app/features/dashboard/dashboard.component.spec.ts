import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { DashboardComponent } from './dashboard.component';

describe('DashboardComponent', () => {
  let fixture: ComponentFixture<DashboardComponent>;
  let component: DashboardComponent;
  let httpMock: HttpTestingController;

  const emptyStats = {
    kpis: {
      saved_jobs: 0,
      active_applications: 0,
      lifetime_applications: 0,
      active_processes: 0,
      interviews: 0,
      offers: 0,
      rejected: 0,
      discarded_jobs: 0,
      conversion_rate: '0.0%',
    },
    monthly_timeline: [],
    daily_timeline: [],
    status_distribution: [],
    portal_distribution: [],
    recent_activity: [],
  };

  function flushAuxCalls(): void {
    for (const url of ['/api/token', '/api/saved', '/api/applications', '/api/discarded']) {
      for (const req of httpMock.match(url)) {
        req.flush({});
      }
    }
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DashboardComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(DashboardComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.match(() => true);
    fixture.destroy();
  });

  it('loads 1m on init and honors 1m, 6m, 12m period switching and manual refresh', () => {
    fixture.detectChanges();
    flushAuxCalls();

    const initReq = httpMock.expectOne('/api/dashboard/stats?period_months=1');
    initReq.flush(emptyStats);

    component.setPeriod('6m');
    const req6 = httpMock.expectOne('/api/dashboard/stats?period_months=6');
    req6.flush(emptyStats);

    component.setPeriod('12m');
    const req12 = httpMock.expectOne('/api/dashboard/stats?period_months=12');
    req12.flush(emptyStats);

    // Refresh button calls loadStats() without args and should preserve selectedPeriod ('12m')
    component.loadStats();
    const refreshReq = httpMock.expectOne('/api/dashboard/stats?period_months=12');
    refreshReq.flush(emptyStats);

    component.setPeriod('1m');
    const reqBackTo1 = httpMock.expectOne('/api/dashboard/stats?period_months=1');
    reqBackTo1.flush(emptyStats);
    expect(component.selectedPeriod()).toBe('1m');
  });

  it('renders LinkedIn portal badges inside portal distribution chart', () => {
    fixture.detectChanges();
    flushAuxCalls();

    const req = httpMock.expectOne('/api/dashboard/stats?period_months=1');
    req.flush({
      ...emptyStats,
      portal_distribution: [
        { portal: 'linkedin_post', label: 'LinkedIn (Post)', count: 2, percentage: 40 },
        { portal: 'linkedin-search', label: 'LinkedIn', count: 3, percentage: 60 },
      ],
    });
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const liBadges = el.querySelectorAll('app-portal-badge i.bi-linkedin');
    expect(liBadges.length).toBe(2);
    expect(el.textContent).toContain('LinkedIn (Post)');
  });
});
