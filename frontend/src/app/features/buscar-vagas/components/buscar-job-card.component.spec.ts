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
    expect(fixture.nativeElement.textContent).toContain('13/11/2026');
  });

  it('resolves effective work model when workplace_type is omitted', () => {
    component.vaga = {
      title: '[Remoto] Backend Developer',
      company: 'RemoteCo',
      portal: 'remotar-search',
      url: 'https://remotar.com.br/job/1',
      location: 'Remoto - Brasil',
      date: '2026-11-15',
    };
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Remoto');
    expect(fixture.nativeElement.textContent).not.toContain('Não informado');
    expect(fixture.nativeElement.textContent).toContain('15/11/2026');
  });
});
