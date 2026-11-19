import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { BuscarVagasComponent } from './buscar-vagas.component';
import { Vaga } from '../../core/models/vaga.model';

describe('BuscarVagasComponent', () => {
  let fixture: ComponentFixture<BuscarVagasComponent>;
  let component: BuscarVagasComponent;
  let httpMock: HttpTestingController;

  function makeVaga(overrides: Partial<Vaga>): Vaga {
    return {
      title: 'Dev Java Júnior',
      company: 'Acme',
      location: 'São Paulo, SP',
      url: 'https://example.com/job/1',
      portal: 'gupy-search',
      workplace_type: 'remoto',
      date: '2026-11-10',
      ...overrides,
    };
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [BuscarVagasComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(BuscarVagasComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    component.state.resetFilters();
    component.filterText = '';
    component.filterModel = '';
    component.filterScore = '';
    component.filterRegion = '';
  });

  afterEach(() => {
    component.state.resetFilters();
    component.filterText = '';
    component.filterModel = '';
    component.filterScore = '';
    component.filterRegion = '';
    component.allVagas.set([]);
    component.onFilterChange();
    httpMock.match(() => true);
    fixture.destroy();
  });

  it('builds dynamic affinityHubs with companiesSample, sampleTitles, scoreText and filters on click', () => {
    fixture.detectChanges();
    httpMock.match(() => true).forEach((req) => req.flush({}));

    component.allVagas.set([
      makeVaga({
        url: 'https://example.com/1',
        company: 'Itaú',
        title: 'Engenheiro Java Jr',
        location: 'São Paulo, SP',
        screening: { score: 82, verdict: 'Strong Fit' },
      }),
      makeVaga({
        url: 'https://example.com/2',
        company: 'Nubank',
        title: 'Dev Backend Kotlin',
        location: 'São Paulo, SP',
        screening: { score: 91, verdict: 'Strong Fit' },
      }),
      makeVaga({
        url: 'https://example.com/3',
        company: 'Hotmart',
        title: 'Dev Fullstack',
        location: 'Belo Horizonte, MG',
      }),
    ]);
    component.onFilterChange();

    const hubs = component.affinityHubs();
    expect(hubs.length).toBe(2);

    const spHub = hubs[0];
    expect(spHub.label).toBe('São Paulo (SP)');
    expect(spHub.count).toBe(2);
    expect(spHub.score).toBe(91);
    expect(spHub.searchTerm).toBe('São Paulo');
    expect(spHub.companiesSample).toBe('Itaú, Nubank');
    expect(spHub.sampleTitles).toBe('Engenheiro Java Jr, Dev Backend Kotlin');
    expect(spHub.scoreText).toBe('Melhor nota 91/100');

    const mgHub = hubs[1];
    expect(mgHub.label).toBe('Minas Gerais (MG)');
    expect(mgHub.scoreText).toBe('Aguardando triagem');

    component.onAffinityClick(spHub);
    expect(component.filterText).toBe('São Paulo');
    expect(component.filteredVagas().length).toBe(2);
    expect(component.filteredVagas().every((v) => v.location?.includes('SP'))).toBeTrue();
  });

  it('filters remote model using resolveEffectiveWorkModel and keeps auxiliary portals visible', () => {
    fixture.detectChanges();
    httpMock.match(() => true).forEach((req) => req.flush({}));

    component.allVagas.set([
      makeVaga({
        url: 'https://example.com/r1',
        title: '[Remoto] Engenheiro(a) Java',
        location: 'Campinas, SP',
        portal: 'github-vagas',
        workplace_type: undefined,
      }),
      makeVaga({
        url: 'https://example.com/r2',
        title: 'Dev Presencial',
        location: 'São Paulo, SP',
        portal: 'gupy-search',
        workplace_type: 'on_site',
      }),
    ]);

    // Desmarca 1 portal principal; github-vagas (portal auxiliar) deve continuar visível
    const nextPortals = new Set(component.selectedPortalIds());
    nextPortals.delete('vagas-search');
    component.state.selectedPortalIds.set(nextPortals);

    component.filterModel = 'remote';
    component.filterText = 'São Paulo';
    component.onFilterChange();

    expect(component.filteredVagas().map((v) => v.url)).toEqual(['https://example.com/r1']);
  });

  it('formats Principal Polo region codes, toggles Filtrar por Maior Nota, and guards 0-portal search', () => {
    fixture.detectChanges();
    httpMock.match(() => true).forEach((req) => req.flush({}));

    component.allVagas.set([
      makeVaga({
        url: 'https://example.com/br-rem-1',
        location: 'Remoto - Brasil',
        portal: 'remotar-search',
        workplace_type: 'remote',
        screening: { score: 88, verdict: 'Strong Fit' },
      }),
      makeVaga({
        url: 'https://example.com/br-rem-2',
        location: 'Brasil (Remoto)',
        portal: 'remotar-search',
        workplace_type: 'remote',
        screening: { score: 62, verdict: 'Good Fit' },
      }),
    ]);
    component.onFilterChange();

    expect(component.leaderPoleName()).toBe('Remoto Brasil');

    component.switchSubtab('mapa');
    component.filterByBestScore();
    expect(component.activeSubtab()).toBe('mapa');
    expect(component.isTriageMode).toBeTrue();
    expect(component.filterSort).toBe('score-desc');
    expect(component.isBestScoreFilterActive()).toBeTrue();

    // Toggling again resets to default
    component.filterByBestScore();
    expect(component.filterSort).toBe('date');
    expect(component.filterScore).toBe('');
    expect(component.isBestScoreFilterActive()).toBeFalse();

    // 0 portals selected -> returns before opening progress panel
    component.showProgressPanel.set(false);
    component.state.selectedPortalIds.set(new Set());
    component.triggerPortalSearch();
    expect(component.searching()).toBeFalse();
    expect(component.showProgressPanel()).toBeFalse();
  });

  it('keeps jobs moved to Me Interessam visible on the map and list with their AI score', () => {
    component.switchSubtab('lista');
    component.currentMapMode = 'brasil';
    fixture.detectChanges();
    httpMock.match(() => true).forEach((req) => req.flush({}));

    // Entering Buscar e Vagas always opens on the World Map
    expect(component.activeSubtab()).toBe('mapa');
    expect(component.currentMapMode).toBe('world');

    const job1 = makeVaga({
      url: 'https://example.com/int-1',
      title: 'Java Developer Remote',
      location: 'San Francisco, CA',
      portal: 'ashby-search',
      screening: { score: 85, verdict: 'Strong Fit', summary: 'Excelente aderência Java' },
    });
    component.allVagas.set([job1]);
    component.onFilterChange();

    component.markInteresse(job1);
    const decideReq = httpMock.expectOne('/api/mark');
    decideReq.flush({ ok: true });
    httpMock.match(() => true).forEach((req) => req.flush({}));

    expect(component.allVagas().length).toBe(1);
    expect(component.allVagas()[0].interested).toBeTrue();
    expect(component.allVagas()[0].status).toBe('interested');
    expect(component.interestedCount()).toBe(1);
    expect(component.mapHighlightedVagas().length).toBe(1);
    expect(component.mapHighlightedVagas()[0].screening?.score).toBe(85);
  });
});
