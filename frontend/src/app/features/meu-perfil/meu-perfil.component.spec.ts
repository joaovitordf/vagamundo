import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MeuPerfilComponent } from './meu-perfil.component';
import { ProfileOrganizeResponse, ProfileResponse } from '../../core/models/vaga.model';

describe('MeuPerfilComponent', () => {
  let fixture: ComponentFixture<MeuPerfilComponent>;
  let component: MeuPerfilComponent;
  let httpMock: HttpTestingController;

  const emptyProfile: ProfileResponse = {
    schema: [
      {
        title: 'Quem é você',
        fields: [
          { key: 'cidade', label: 'Cidade e UF', type: 'text', placeholder: '' },
          { key: 'cargos', label: 'Cargos-alvo', type: 'lines', placeholder: '' },
          { key: 'senioridade', label: 'Senioridade', type: 'multi', options: ['junior', 'pleno', 'senior'] },
          { key: 'comportamental', label: 'Perfil comportamental', type: 'textarea', placeholder: '' },
        ],
      },
    ],
    answers: {},
    files: { cv: [], linkedin: [] },
    privacy: { status: 'local' },
    ready: false,
    profile: '',
    report: '',
  };

  const organizedProfile: ProfileResponse = {
    ...emptyProfile,
    answers: {
      cidade: 'Campinas - SP',
      cargos: ['Desenvolvedora Python'],
      senioridade: ['senior'],
      comportamental: 'Perfil analítico e colaborativo.',
    },
    files: {
      cv: [{ name: 'joana.pdf', size: 1234 }],
      linkedin: [],
    },
    ready: true,
    profile: '## Perfil consolidado\n\n- Joana Silva',
    report: '## Perfil consolidado\n\n- Joana Silva',
  };

  function flushBootstrap(): void {
    for (const url of ['/api/token', '/api/saved', '/api/applications', '/api/discarded']) {
      for (const req of httpMock.match(url)) {
        req.flush({});
      }
    }
  }

  function makePdfEvent(name = 'joana.pdf'): Event {
    const file = new File(['%PDF-1.4 fake content'], name, { type: 'application/pdf' });
    const input = document.createElement('input');
    input.type = 'file';
    Object.defineProperty(input, 'files', { value: [file], writable: false });
    return { target: input } as unknown as Event;
  }

  const waitForFileReader = () => new Promise<void>((resolve) => setTimeout(resolve, 40));

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MeuPerfilComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(MeuPerfilComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.match(() => true);
    fixture.destroy();
  });

  it('auto-organizes profile after PDF upload when autoOrganizeOnUpload is enabled', async () => {
    fixture.detectChanges();
    flushBootstrap();
    httpMock.expectOne('/api/profile').flush(emptyProfile);
    fixture.detectChanges();

    component.autoOrganizeOnUpload = true;
    component.triggerUpload('cv');
    component.onFileSelected(makePdfEvent('joana.pdf'));
    await waitForFileReader();

    const uploadReq = httpMock.expectOne('/api/upload');
    expect(uploadReq.request.method).toBe('POST');
    uploadReq.flush({ ok: true, file: 'joana.pdf' });

    httpMock.expectOne('/api/profile?refresh=1').flush({
      ...emptyProfile,
      files: organizedProfile.files,
    });

    const orgReq = httpMock.expectOne('/api/profile/organize');
    expect(orgReq.request.method).toBe('POST');
    expect(orgReq.request.body).toEqual({ overwrite: false, confirm: false });

    const organizeResp: ProfileOrganizeResponse = {
      ok: true,
      organized: true,
      updated_fields: ['cidade', 'cargos', 'senioridade'],
      profile: organizedProfile,
    };
    orgReq.flush(organizeResp);
    fixture.detectChanges();

    expect(component.formValues['cidade']).toBe('Campinas - SP');
    expect(component.formValues['cargos']).toBe('Desenvolvedora Python');
    expect(component.formValues['senioridade']).toEqual(['senior']);
    expect(component.profileData()?.ready).toBeTrue();
    expect(component.organizeStatus()).toContain('3 campo(s) do formulário preenchido(s)');
  });

  it('keeps uploaded PDF and shows friendly fallback when AI is unconfigured', async () => {
    fixture.detectChanges();
    flushBootstrap();
    httpMock.expectOne('/api/profile').flush(emptyProfile);
    fixture.detectChanges();

    component.triggerUpload('cv');
    component.onFileSelected(makePdfEvent('joana.pdf'));
    await waitForFileReader();

    httpMock.expectOne('/api/upload').flush({ ok: true, file: 'joana.pdf' });
    httpMock.expectOne('/api/profile?refresh=1').flush({
      ...emptyProfile,
      files: organizedProfile.files,
    });

    const orgReq = httpMock.expectOne('/api/profile/organize');
    orgReq.flush({
      ok: false,
      organized: false,
      reason: 'ai_unconfigured',
      detail: 'Nenhum provedor de IA configurado',
      updated_fields: [],
      profile: { ...emptyProfile, files: organizedProfile.files },
    } as ProfileOrganizeResponse);
    fixture.detectChanges();

    expect(component.organizeStatus()).toContain('Nenhum provedor de IA configurado');
    expect(component.isOrganizing()).toBeFalse();
  });

  it('skips auto-organize when toggle is disabled and passes overwrite flag on manual click', async () => {
    fixture.detectChanges();
    flushBootstrap();
    httpMock.expectOne('/api/profile').flush({ ...emptyProfile, files: organizedProfile.files });
    fixture.detectChanges();

    component.autoOrganizeOnUpload = false;
    component.triggerUpload('cv');
    component.onFileSelected(makePdfEvent('outro.pdf'));
    await waitForFileReader();

    httpMock.expectOne('/api/upload').flush({ ok: true, file: 'outro.pdf' });
    httpMock.expectNone('/api/profile/organize');
    httpMock.expectOne('/api/profile?refresh=1').flush({ ...emptyProfile, files: organizedProfile.files });

    component.overwriteExistingFields = true;
    component.organizeFromDocuments();

    const manualReq = httpMock.expectOne('/api/profile/organize');
    expect(manualReq.request.body).toEqual({ overwrite: true, confirm: false });
    manualReq.flush({
      ok: true,
      organized: true,
      updated_fields: ['cargos'],
      profile: organizedProfile,
    } as ProfileOrganizeResponse);
    fixture.detectChanges();

    expect(component.formValues['cargos']).toBe('Desenvolvedora Python');
  });
});
