import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { CandidaturasComponent } from './candidaturas.component';

describe('CandidaturasComponent', () => {
  let fixture: ComponentFixture<CandidaturasComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CandidaturasComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(CandidaturasComponent);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.match(() => true);
    fixture.destroy();
  });

  it('renders LinkedIn portal badge with bi-linkedin icon for LinkedIn applications', () => {
    fixture.detectChanges();

    for (const req of httpMock.match('/api/token')) {
      req.flush({ token: 'tok' });
    }
    for (const req of httpMock.match('/api/saved')) {
      req.flush({ saved: [] });
    }
    for (const req of httpMock.match('/api/discarded')) {
      req.flush({ discarded: [] });
    }
    for (const req of httpMock.match('/api/applications')) {
      req.flush({
        applications: [
          {
            id: 1,
            company: 'LinkedInHire',
            role: 'Java / Angular Dev',
            channel: 'linkedin_post',
            portal: 'linkedin_post',
            contact_channel: 'recruiter_email',
            contacted_email: 'jobs@linkedinhire.dev',
            status: 'applied',
            applied_date: '2026-11-13',
          },
        ],
      });
    }
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    const badge = el.querySelector('app-portal-badge [data-portal="linkedin_post"]') as HTMLElement;
    expect(badge).not.toBeNull();
    expect(badge.querySelector('i.bi-linkedin')).not.toBeNull();
    expect(badge.textContent).toContain('LinkedIn (Post)');
  });
});
