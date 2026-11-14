import { ComponentFixture, TestBed } from '@angular/core/testing';
import { BuscarJobCardComponent } from './buscar-job-card.component';

describe('BuscarJobCardComponent', () => {
  let fixture: ComponentFixture<BuscarJobCardComponent>;
  let component: BuscarJobCardComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [BuscarJobCardComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(BuscarJobCardComponent);
    component = fixture.componentInstance;
  });

  it('renders LinkedIn portal badge with bi-linkedin icon', () => {
    component.vaga = {
      title: 'Java Developer',
      company: 'LinkedIn Co',
      portal: 'linkedin-search',
      url: 'https://www.linkedin.com/jobs/view/123',
      location: 'Remoto',
      workplace_type: 'remote',
      date: '2026-11-13',
    };
    fixture.detectChanges();

    const badge = fixture.nativeElement.querySelector('app-portal-badge [data-portal="linkedin-search"]') as HTMLElement;
    expect(badge).not.toBeNull();
    expect(badge.querySelector('i.bi-linkedin')).not.toBeNull();
    expect(badge.textContent).toContain('LinkedIn');
  });
});
