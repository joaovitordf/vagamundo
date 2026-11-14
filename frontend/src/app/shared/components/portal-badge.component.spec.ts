import { ComponentFixture, TestBed } from '@angular/core/testing';
import { PortalBadgeComponent } from './portal-badge.component';

describe('PortalBadgeComponent', () => {
  let fixture: ComponentFixture<PortalBadgeComponent>;
  let component: PortalBadgeComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PortalBadgeComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(PortalBadgeComponent);
    component = fixture.componentInstance;
  });

  it('does not render when portal and labelOverride are empty', () => {
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.portal-badge')).toBeNull();
  });

  it('renders LinkedIn post badge with bi-linkedin icon and data-portal="linkedin_post"', () => {
    component.portal = 'linkedin_post';
    fixture.detectChanges();

    const badge = fixture.nativeElement.querySelector('.portal-badge') as HTMLElement;
    expect(badge).not.toBeNull();
    expect(badge.getAttribute('data-portal')).toBe('linkedin_post');
    expect(badge.classList).toContain('portal-badge--linkedin');
    expect(badge.textContent).toContain('LinkedIn (Post)');
    expect(badge.querySelector('i.bi-linkedin')).not.toBeNull();
  });

  it('renders LinkedIn search badge with bi-linkedin icon and compact mode', () => {
    component.portal = 'linkedin-search';
    component.compact = true;
    fixture.detectChanges();

    const badge = fixture.nativeElement.querySelector('.portal-badge') as HTMLElement;
    expect(badge.getAttribute('data-portal')).toBe('linkedin-search');
    expect(badge.classList).toContain('portal-badge--compact');
    expect(badge.classList).toContain('portal-badge--linkedin');
    expect(badge.textContent).toContain('LinkedIn');
    expect(badge.querySelector('i.bi-linkedin')).not.toBeNull();
  });

  it('renders non-LinkedIn portals with matching icon and supports labelOverride', () => {
    component.portal = 'github-vagas';
    fixture.detectChanges();
    let badge = fixture.nativeElement.querySelector('.portal-badge') as HTMLElement;
    expect(badge.querySelector('i.bi-github')).not.toBeNull();

    component.portal = 'recruiter_email';
    component.labelOverride = 'Contato direto';
    fixture.detectChanges();
    badge = fixture.nativeElement.querySelector('.portal-badge') as HTMLElement;
    expect(badge.textContent).toContain('Contato direto');
    expect(badge.querySelector('i.bi-envelope-paper')).not.toBeNull();
  });
});
