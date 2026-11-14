import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ConfiguracoesComponent } from './configuracoes.component';
import { SettingsResponse } from '../../core/models/vaga.model';

describe('ConfiguracoesComponent', () => {
  let fixture: ComponentFixture<ConfiguracoesComponent>;
  let component: ConfiguracoesComponent;
  let httpMock: HttpTestingController;

  const mockSettings: SettingsResponse = {
    provider: 'auto',
    consent: true,
    active: {
      provider: 'openai',
      via: 'api_key',
      label: 'OpenAI GPT',
      model: 'gpt-4o-mini',
      available: true,
    },
    providers: [
      {
        id: 'gemini',
        label: 'Google Gemini',
        model: 'gemini-2.5-flash',
        default_model: 'gemini-2.5-flash',
        suggested_models: ['gemini-2.5-flash', 'gemini-2.5-pro'],
        has_key: false,
        key_hint: '',
        cli_name: 'gemini',
        cli_found: false,
        mode: 'none',
        base_url: '',
        supports_base_url: false,
      },
      {
        id: 'openai',
        label: 'OpenAI / Compatível',
        model: 'gpt-4o-mini',
        default_model: 'gpt-4o-mini',
        suggested_models: ['gpt-4o-mini', 'gpt-4o'],
        has_key: true,
        key_hint: 'sk-...abcd',
        cli_found: false,
        mode: 'api',
        base_url: 'https://api.openai.com/v1',
        supports_base_url: true,
      },
      {
        id: 'claude',
        label: 'Anthropic Claude',
        model: 'claude-sonnet-4',
        default_model: 'claude-sonnet-4',
        suggested_models: ['claude-sonnet-4'],
        has_key: false,
        key_hint: '',
        cli_name: 'claude',
        cli_found: true,
        mode: 'cli',
        base_url: '',
        supports_base_url: false,
      },
    ],
  };

  function flushBootstrap(): void {
    for (const url of ['/api/token', '/api/saved', '/api/applications', '/api/discarded']) {
      for (const req of httpMock.match(url)) {
        req.flush({});
      }
    }
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ConfiguracoesComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(ConfiguracoesComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.match(() => true);
    fixture.destroy();
  });

  it('renders providers dynamically and reports hasProviderKey accurately when provider is auto', () => {
    fixture.detectChanges();
    flushBootstrap();

    const getReq = httpMock.expectOne('/api/settings');
    getReq.flush(mockSettings);
    fixture.detectChanges();

    expect(component.activeProviderLabel()).toBe('OpenAI GPT');
    expect(component.activeModelLabel()).toBe('gpt-4o-mini');
    expect(component.hasProviderKey('openai')).toBeTrue();
    expect(component.hasProviderKey('gemini')).toBeFalse();

    const cards = fixture.nativeElement.querySelectorAll('.provider-card') as NodeListOf<HTMLElement>;
    expect(cards.length).toBe(3);
    expect(cards[1].textContent).toContain('sk-...abcd');
    expect(cards[2].textContent).toContain('CLI local');
    expect(fixture.nativeElement.querySelector('#baseurl-openai')).toBeTruthy();

    component.providerKeys['gemini'] = 'new-gemini-key';
    component.providerModels['openai'] = 'gpt-4o';
    component.clearKeyFlags['openai'] = true;
    component.saveSettings();

    const postReq = httpMock.expectOne('/api/settings');
    expect(postReq.request.method).toBe('POST');
    expect(postReq.request.body.provider).toBe('auto');
    expect(postReq.request.body.providers['gemini'].api_key).toBe('new-gemini-key');
    expect(postReq.request.body.providers['openai'].model).toBe('gpt-4o');
    expect(postReq.request.body.providers['openai'].clear_key).toBeTrue();
    postReq.flush(mockSettings);
  });
});
