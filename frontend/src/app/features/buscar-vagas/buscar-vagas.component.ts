import { Component, OnInit, ElementRef, ViewChild, AfterViewInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';
import { Vaga } from '../../core/models/vaga.model';

const PORTAIS: Record<string, string> = {
  'gupy-search': 'Gupy',
  'solides-search': 'Sólides',
  'vagas-search': 'VAGAS.com',
  'infojobs-search': 'InfoJobs',
  'remotar-search': 'Remotar',
  'greenhouse-search': 'Greenhouse',
  'programathor-search': 'Programathor',
  'geekhunter-search': 'GeekHunter',
  'michaelpage-search': 'Michael Page',
  'roberthalf-search': 'Robert Half',
  'trampos-search': 'Trampos',
  'pcd-search': 'PCD Online',
  'agrobase-search': 'Agrobase',
  'agrosearch-search': 'AGROSearch',
  'digai-search': 'DigAÍ',
  'empregos-search': 'Empregos.com.br',
  'linkedin-search': 'LinkedIn',
  'freehire-search': 'freehire',
  'hh-search': 'HeadHunter (hh.ru)',
  'habrcareer-search': 'Habr Career',
  'google-careers': 'Google Careers',
  'eures': 'EURES (Europa)',
};

const MODELOS: Record<string, string> = {
  remote: 'Remoto',
  hybrid: 'Híbrido',
  'on-site': 'Presencial',
  none: 'Não informado'
};

const BR_UF_WORDS = [
  { uf: 'SP', name: 'São Paulo', words: ['são paulo', 'sao paulo', 'sp', 'campinas', 'santos', 'sorocaba', 'ribeirão preto', 'são josé dos campos', 'barueri', 'osasco', 'são bernardo', 'jundiaí'] },
  { uf: 'MG', name: 'Minas Gerais', words: ['minas gerais', 'mg', 'belo horizonte', 'uberlândia', 'uberlandia', 'juiz de fora', 'contagem', 'betim'] },
  { uf: 'RJ', name: 'Rio de Janeiro', words: ['rio de janeiro', 'rj', 'niterói', 'niteroi', 'petrópolis'] },
  { uf: 'PR', name: 'Paraná', words: ['paraná', 'parana', 'pr', 'curitiba', 'maringá', 'londrina', 'cascavel'] },
  { uf: 'SC', name: 'Santa Catarina', words: ['santa catarina', 'sc', 'florianópolis', 'florianopolis', 'joinville', 'blumenau', 'chapecó', 'itajai', 'itajaí'] },
  { uf: 'RS', name: 'Rio Grande do Sul', words: ['rio grande do sul', 'rs', 'porto alegre', 'caxias do sul', 'canoas', 'são leopoldo', 'novo hamburgo'] },
  { uf: 'BA', name: 'Bahia', words: ['bahia', 'ba', 'salvador', 'feira de santana', 'lauro de freitas'] },
  { uf: 'PE', name: 'Pernambuco', words: ['pernambuco', 'pe', 'recife', 'olinda', 'jaboatao'] },
  { uf: 'CE', name: 'Ceará', words: ['ceará', 'ceara', 'ce', 'fortaleza'] },
  { uf: 'DF', name: 'Distrito Federal', words: ['distrito federal', 'df', 'brasília', 'brasilia'] },
  { uf: 'GO', name: 'Goiás', words: ['goiás', 'goias', 'go', 'goiânia', 'goiania', 'anápolis'] },
  { uf: 'ES', name: 'Espírito Santo', words: ['espírito santo', 'espirito santo', 'es', 'vitória', 'vitoria', 'vila velha', 'serra'] },
  { uf: 'MT', name: 'Mato Grosso', words: ['mato grosso', 'mt', 'cuiabá', 'cuiaba'] },
  { uf: 'MS', name: 'Mato Grosso do Sul', words: ['mato grosso do sul', 'ms', 'campo grande', 'dourados'] },
  { uf: 'AM', name: 'Amazonas', words: ['amazonas', 'am', 'manaus'] },
  { uf: 'PA', name: 'Pará', words: ['pará', 'belem', 'belém'] },
  { uf: 'RN', name: 'Rio Grande do Norte', words: ['rio grande do norte', 'rn', 'natal'] },
  { uf: 'PB', name: 'Paraíba', words: ['paraíba', 'paraiba', 'pb', 'joão pessoa', 'campina grande'] },
  { uf: 'AL', name: 'Alagoas', words: ['alagoas', 'al', 'maceió', 'maceio'] },
  { uf: 'SE', name: 'Sergipe', words: ['sergipe', 'se', 'aracaju'] },
  { uf: 'PI', name: 'Piauí', words: ['piauí', 'piaui', 'pi', 'teresina'] },
  { uf: 'MA', name: 'Maranhão', words: ['maranhão', 'maranhao', 'ma', 'são luís', 'sao luis'] },
  { uf: 'RO', name: 'Rondônia', words: ['rondônia', 'rondonia', 'ro', 'porto velho'] },
  { uf: 'TO', name: 'Tocantins', words: ['tocantins', 'to', 'palmas'] },
  { uf: 'AC', name: 'Acre', words: ['acre', 'ac', 'rio branco'] },
  { uf: 'AP', name: 'Amapá', words: ['amapá', 'amapa', 'ap', 'macapá', 'macapa'] },
  { uf: 'RR', name: 'Roraima', words: ['roraima', 'rr', 'boa vista'] }
];

const WORLD_PATTERNS = [
  { code: 'DE', name: 'Alemanha', scope: 'europa', words: ['germany', 'deutschland', 'alemanha', 'berlin', 'munich', 'münchen', 'frankfurt', 'hamburg', 'stuttgart', 'kiel'] },
  { code: 'NL', name: 'Holanda', scope: 'europa', words: ['netherlands', 'holanda', 'países baixos', 'amsterdam', 'rotterdam', 'eindhoven', 'utrecht'] },
  { code: 'GB', name: 'Reino Unido', scope: 'europa', words: ['united kingdom', 'reino unido', 'england', 'scotland', 'wales', 'london', 'manchester', 'cambridge', 'oxford'] },
  { code: 'ES', name: 'Espanha', scope: 'europa', words: ['spain', 'espanha', 'españa', 'madrid', 'barcelona', 'valencia', 'seville', 'bilbao'] },
  { code: 'FR', name: 'França', scope: 'europa', words: ['france', 'frança', 'paris', 'lyon', 'toulouse', 'marseille', 'nice', 'bordeaux'] },
  { code: 'IT', name: 'Itália', scope: 'europa', words: ['italy', 'itália', 'italia', 'milan', 'milano', 'rome', 'roma', 'turin'] },
  { code: 'PL', name: 'Polônia', scope: 'europa', words: ['poland', 'polônia', 'polska', 'warsaw', 'warszawa', 'krakow', 'kraków', 'wroclaw', 'gdansk'] },
  { code: 'CH', name: 'Suíça', scope: 'europa', words: ['switzerland', 'suíça', 'suica', 'schweiz', 'zürich', 'zurich', 'geneva'] },
  { code: 'SE', name: 'Suécia', scope: 'europa', words: ['sweden', 'suécia', 'suecia', 'stockholm', 'gothenburg', 'göteborg'] },
  { code: 'FI', name: 'Finlândia', scope: 'europa', words: ['finland', 'finlândia', 'finlandia', 'helsinki', 'espoo'] },
  { code: 'PT', name: 'Portugal', scope: 'europa', words: ['portugal', 'lisbon', 'lisboa', 'porto', 'braga', 'coimbra'] },
  { code: 'IE', name: 'Irlanda', scope: 'europa', words: ['ireland', 'irlanda', 'dublin', 'cork', 'galway'] },
  { code: 'BE', name: 'Bélgica', scope: 'europa', words: ['belgium', 'bélgica', 'belgica', 'brussels', 'bruxelles'] },
  { code: 'AT', name: 'Áustria', scope: 'europa', words: ['austria', 'áustria', 'vienna', 'wien'] },
  { code: 'NO', name: 'Noruega', scope: 'europa', words: ['norway', 'noruega', 'oslo', 'bergen'] },
  { code: 'DK', name: 'Dinamarca', scope: 'europa', words: ['denmark', 'dinamarca', 'copenhagen'] },
  { code: 'CZ', name: 'República Tcheca', scope: 'europa', words: ['czech', 'czechia', 'prague', 'praha'] },
  { code: 'RO', name: 'Romênia', scope: 'europa', words: ['romania', 'romênia', 'bucharest'] },
  { code: 'HU', name: 'Hungria', scope: 'europa', words: ['hungary', 'hungria', 'budapest'] },
  { code: 'CA', name: 'Canadá', scope: 'global', words: ['canada', 'canadá', 'toronto', 'ontario', 'vancouver', 'montreal'] },
  { code: 'US', name: 'Estados Unidos', scope: 'global', words: ['united states', 'estados unidos', 'usa', 'u.s.', 'mountain view', 'sunnyvale', 'san francisco', 'california', 'new york', 'seattle', 'austin', 'boston', 'chicago'] },
  { code: 'RU', name: 'Rússia', scope: 'global', words: ['russia', 'rússia', 'россия', 'moscow', 'москва', 'saint petersburg'] },
  { code: 'JP', name: 'Japão', scope: 'global', words: ['japan', 'japão', 'tokyo', 'osaka'] },
  { code: 'SG', name: 'Singapura', scope: 'global', words: ['singapore', 'singapura', 'cingapura'] },
  { code: 'AU', name: 'Austrália', scope: 'global', words: ['australia', 'austrália', 'sydney', 'melbourne'] },
  { code: 'IN', name: 'Índia', scope: 'global', words: ['india', 'índia', 'bangalore', 'bengaluru', 'hyderabad'] }
];

const BR_PORTALS = new Set([
  'gupy-search', 'solides-search', 'vagas-search', 'infojobs-search', 'remotar-search',
  'programathor-search', 'geekhunter-search', 'trampos-search', 'pcd-search',
  'agrobase-search', 'agrosearch-search', 'digai-search', 'empregos-search'
]);

const SVG_NS = 'http://www.w3.org/2000/svg';

interface GeoResolution {
  scope: 'brasil' | 'europa' | 'global';
  countryCode: string;
  code: string;
  label: string;
  isRemote: boolean;
  remoteBucket: string | null;
}

interface ActiveGeoFilter {
  type: 'country' | 'uf' | 'remote';
  code: string;
  name: string;
  count: number;
}

@Component({
  selector: 'app-buscar-vagas',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './buscar-vagas.component.html',
  styleUrl: './buscar-vagas.component.css'
})
export class BuscarVagasComponent implements OnInit, AfterViewInit {
  private readonly api = inject(ApiService);

  @ViewChild('mapWorldContainer') mapWorldContainer!: ElementRef<HTMLDivElement>;
  @ViewChild('mapBrasilContainer') mapBrasilContainer!: ElementRef<HTMLDivElement>;

  allVagas = signal<Vaga[]>([]);
  filteredVagas = signal<Vaga[]>([]);
  activeSubtab = signal<'mapa' | 'lista'>('mapa');
  currentMapMode: 'world' | 'brasil' = 'world';

  // Filtros
  filterText = '';
  filterFocus = 'all';
  filterModel = '';
  filterRegion = '';
  filterJobAge = '';
  filterScore = '';
  filterSort = 'date';
  filterNoWarn = false;
  filterVisa = false;

  cvAreaBadge = signal<string>('');
  private cvAreasList: any[] = [];
  private cvAreaQueue: any[] = [];
  private lastPickedAreaId: string | null = null;

  // Mapa & Dados Geográficos
  private geoData: any = null;
  activeGeoFilter: ActiveGeoFilter | null = null;
  isTriageMode = false;
  remoteCounts: Record<string, number> = { REMOTO_BR: 0, EU_REMOTE: 0, GLOBAL_REMOTE: 0 };
  remoteScores: Record<string, number> = { REMOTO_BR: -1, EU_REMOTE: -1, GLOBAL_REMOTE: -1 };

  // Status de Busca & Triagem
  searching = signal<boolean>(false);
  searchStatus = signal<string>('');
  searchError = signal<string>('');
  searchSummary = signal<string>('');
  batchRunning = signal<boolean>(false);
  batchStatus = signal<string>('');
  batchScope = 'all-visible';

  selectedUrls = new Set<string>();

  ngOnInit(): void {
    this.loadCvAreas();
    // Só restaura vagas se o usuário já tiver clicado em "Buscar vagas" nesta sessão
    if (this.api.hasSearchedInSession()) {
      this.allVagas.set(this.api.sessionVagas());
      this.onFilterChange();
      this.checkInitialStatus();
    }
  }

  ngAfterViewInit(): void {
    this.loadGeoData();
  }

  loadCvAreas(): void {
    this.api.getCvAreas().subscribe({
      next: (res) => {
        if (res && Array.isArray(res.areas)) {
          this.cvAreasList = res.areas;
        }
      },
      error: () => {}
    });
  }

  pickRandomCvArea(): void {
    if (!this.cvAreasList.length) return;
    if (this.cvAreaQueue.length === 0) {
      const copy = [...this.cvAreasList];
      for (let i = copy.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [copy[i], copy[j]] = [copy[j], copy[i]];
      }
      if (copy.length > 1 && copy[0].id === this.lastPickedAreaId) {
        const swapIdx = 1 + Math.floor(Math.random() * (copy.length - 1));
        [copy[0], copy[swapIdx]] = [copy[swapIdx], copy[0]];
      }
      this.cvAreaQueue = copy;
    }
    const picked = this.cvAreaQueue.shift();
    if (!picked) return;
    this.lastPickedAreaId = picked.id;

    this.filterText = (picked.keywords || []).join(', ');
    this.cvAreaBadge.set(`Área CV: ${picked.label || picked.title}`);
    this.onFilterChange();
  }

  clearTextFilter(): void {
    this.filterText = '';
    this.cvAreaBadge.set('');
    this.onFilterChange();
  }

  loadResults(): void {
    this.api.getResults().subscribe({
      next: (res) => {
        this.allVagas.set(res.new || []);
        this.onFilterChange();
      },
      error: (err) => console.error('Erro ao carregar resultados:', err)
    });
  }

  loadGeoData(): void {
    this.api.getGeo().subscribe({
      next: (data) => {
        this.geoData = data;
        this.updateMap();
      },
      error: (err) => console.error('Erro ao carregar geo data:', err)
    });
  }

  checkInitialStatus(): void {
    this.api.getSearchStatus().subscribe({
      next: (st) => {
        if (st && st.search && st.search.error) {
          this.searchError.set('A busca não terminou: ' + st.search.error);
        }
        if (st && st.search && st.search.summary) {
          this.searchSummary.set(st.search.summary);
        }
      },
      error: () => {}
    });
  }

  triggerPortalSearch(): void {
    this.searching.set(true);
    this.searchStatus.set('Iniciando busca nos portais…');
    this.searchError.set('');
    this.searchSummary.set('');

    // Ao iniciar busca nos portais, limpamos filtros locais de texto e geo para exibir todas as vagas retornadas
    this.filterText = '';
    this.cvAreaBadge.set('');
    this.activeGeoFilter = null;

    const payload = {
      all: true,
      jobage: Number(this.filterJobAge) || 14,
      focus: this.filterFocus
    };

    this.api.startSearch(payload).subscribe({
      next: () => {
        this.pollSearchStatus();
      },
      error: (err) => {
        this.searching.set(false);
        this.searchStatus.set('');
        this.searchError.set('Erro ao iniciar busca: ' + (err?.error?.error || err?.message || 'Falha na comunicação'));
      }
    });
  }

  private pollSearchStatus(): void {
    const interval = setInterval(() => {
      this.api.getSearchStatus().subscribe({
        next: (st) => {
          const job = st.search;
          if (job && job.running) {
            this.searchStatus.set(`Buscando desde ${job.started?.slice(11, 16) || ''}…`);
          } else {
            clearInterval(interval);
            this.searching.set(false);
            if (job && job.error) {
              this.searchError.set('A busca não terminou: ' + job.error);
              this.searchStatus.set('');
            } else {
              this.searchStatus.set('Busca concluída!');
            }
            if (job && job.summary) {
              this.searchSummary.set(job.summary);
            }
            this.loadResults();
          }
        },
        error: () => {
          clearInterval(interval);
          this.searching.set(false);
        }
      });
    }, 2000);
  }

  getBaseFilteredVagas(): Vaga[] {
    const rawText = this.filterText.trim();
    const model = this.filterModel;
    const focus = this.filterFocus;
    const days = this.filterJobAge ? Number(this.filterJobAge) : null;
    const score = this.filterScore;
    const nowarn = this.filterNoWarn;
    const visaOnly = this.filterVisa;
    const region = this.filterRegion;

    const today = new Date();
    today.setHours(23, 59, 59, 999);
    const fold = (s: string) => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();

    return this.allVagas().filter((r) => {
      const geo = this.resolveGeo(r);

      if (region) {
        if (region === 'remote' && !geo.isRemote) return false;
        if (region === 'brasil' && geo.scope !== 'brasil') return false;
        if (region === 'europa' && geo.scope !== 'europa') return false;
        if (region === 'global' && geo.scope !== 'global') return false;
      }

      if (nowarn && this.getWarning(r)) return false;
      if (visaOnly && !this.hasVisa(r)) return false;

      if (model) {
        if (model === 'none' ? Boolean(r.workplace_type) : r.workplace_type !== model) return false;
      }

      if (focus && focus !== 'all') {
        if (focus === 'google') {
          if (r.portal !== 'google' && r.portal !== 'google-careers') return false;
        } else if (focus === 'europa') {
          if (r.portal !== 'europa' && r.portal !== 'eures') return false;
        } else if (r.portal !== focus) {
          return false;
        }
      }

      if (days && r.date) {
        const diffDays = Math.floor((today.getTime() - new Date(r.date + 'T00:00:00').getTime()) / 86400000);
        if (diffDays > days) return false;
      }

      if (score) {
        const s = r.screening?.score;
        if (score === 'triadas' && (s === undefined || s === null)) return false;
        if (score === 'high' && (s === undefined || s < 80)) return false;
        if (score === 'med' && (s === undefined || s < 60)) return false;
        if (score === 'low' && (s === undefined || s >= 60 || s < 40)) return false;
      }

      if (rawText) {
        const terms = rawText.split(',').map(t => fold(t.trim())).filter(Boolean);
        if (terms.length > 0) {
          const desc = r.description ? (r.description.length > 2500 ? r.description.slice(0, 2500) : r.description) : '';
          const tags = Array.isArray((r as any).tags) ? (r as any).tags.join(' ') : '';
          const skills = Array.isArray((r as any).skills) ? (r as any).skills.join(' ') : '';
          const hay = fold(`${r.title || ''} ${r.company || ''} ${r.location || ''} ${r.seniority || ''} ${desc} ${tags} ${skills}`);
          if (!terms.some(t => hay.includes(t))) return false;
        }
      }

      return true;
    });
  }

  onFilterChange(): void {
    const base = this.getBaseFilteredVagas();

    let filtered = base;
    if (this.activeGeoFilter) {
      filtered = base.filter((r) => {
        const geo = this.resolveGeo(r);
        if (this.activeGeoFilter!.type === 'remote') {
          return geo.remoteBucket === this.activeGeoFilter!.code || geo.code === this.activeGeoFilter!.code;
        } else if (this.activeGeoFilter!.type === 'uf') {
          return geo.countryCode === 'BR' && geo.code === this.activeGeoFilter!.code;
        } else if (this.activeGeoFilter!.type === 'country') {
          return geo.countryCode === this.activeGeoFilter!.code;
        }
        return true;
      });
    }

    if (this.filterSort === 'score-desc') {
      filtered.sort((a, b) => (b.screening?.score || -1) - (a.screening?.score || -1));
    } else if (this.filterSort === 'score-asc') {
      filtered.sort((a, b) => (a.screening?.score || 999) - (b.screening?.score || 999));
    }

    this.filteredVagas.set(filtered);
    this.updateMap();
  }

  resetAllFilters(): void {
    this.filterText = '';
    this.cvAreaBadge.set('');
    this.filterModel = '';
    this.filterFocus = 'all';
    this.filterRegion = '';
    this.filterJobAge = '';
    this.filterScore = '';
    this.filterNoWarn = false;
    this.filterVisa = false;
    this.activeGeoFilter = null;
    this.onFilterChange();
  }

  switchSubtab(tab: 'mapa' | 'lista'): void {
    this.activeSubtab.set(tab);
    if (tab === 'mapa') {
      setTimeout(() => this.updateMap(), 50);
    }
  }

  switchMapMode(mode: 'world' | 'brasil'): void {
    this.currentMapMode = mode;
    if (mode === 'brasil' && (!this.activeGeoFilter || this.activeGeoFilter.type === 'country')) {
      const brCnt = this.allVagas().filter(r => this.resolveGeo(r).countryCode === 'BR').length;
      this.activeGeoFilter = { type: 'country', code: 'BR', name: 'Brasil (Todos os Estados)', count: brCnt };
    }
    this.updateMap();
  }

  selectRemoteChip(code: string, name: string): void {
    if (this.activeGeoFilter?.type === 'remote' && this.activeGeoFilter.code === code) {
      this.activeGeoFilter = null;
    } else {
      const cnt = this.remoteCounts[code] || 0;
      this.activeGeoFilter = { type: 'remote', code, name, count: cnt };
    }
    this.onFilterChange();
  }

  clearGeoFilter(): void {
    this.activeGeoFilter = null;
    this.onFilterChange();
  }

  toggleTriageMode(): void {
    this.isTriageMode = !this.isTriageMode;
    this.updateMap();
  }

  mapIndicatorText(): string {
    if (this.activeGeoFilter) {
      return `${this.activeGeoFilter.name} (${this.activeGeoFilter.count} vagas)`;
    }
    if (this.filteredVagas().length < this.allVagas().length) {
      return `Exibindo ${this.filteredVagas().length} de ${this.allVagas().length} vagas (filtros ativos)`;
    }
    return 'Todas as localidades';
  }

  localVagas(): Vaga[] {
    if (!this.activeGeoFilter) return [];
    return this.filteredVagas();
  }

  hasTriagedJobs(): boolean {
    return this.allVagas().some(r => r.screening && typeof r.screening.score === 'number');
  }

  triagedCount(): number {
    return this.allVagas().filter(r => r.screening && typeof r.screening.score === 'number').length;
  }

  highFitCount(): number {
    return this.allVagas().filter(r => r.screening && (r.screening.score || 0) >= 75).length;
  }

  mappedLocationsCount(): number {
    const locs = new Set<string>();
    this.filteredVagas().forEach(r => {
      const g = this.resolveGeo(r);
      if (g.code) locs.add(g.code);
    });
    return locs.size;
  }

  leaderPoleName(): string {
    const counts: Record<string, number> = {};
    this.filteredVagas().forEach(r => {
      const g = this.resolveGeo(r);
      if (g.code) counts[g.code] = (counts[g.code] || 0) + 1;
    });
    let max = 0;
    let leader = 'Diversos Polos';
    Object.entries(counts).forEach(([k, v]) => {
      if (v > max) {
        max = v;
        leader = k;
      }
    });
    return leader;
  }


  affinityHubs(): any[] {
    const list = this.filteredVagas();
    const hubs: Record<string, { label: string; count: number; score: number; key: string }> = {};

    list.forEach(r => {
      const geo = this.resolveGeo(r);
      const k = geo.label || geo.code || 'Outros';
      const sc = (r.screening && typeof r.screening.score === 'number') ? r.screening.score : -1;
      if (!hubs[k]) {
        hubs[k] = { label: k, count: 0, score: -1, key: k };
      }
      hubs[k].count++;
      if (sc > hubs[k].score) hubs[k].score = sc;
    });

    return Object.values(hubs)
      .sort((a, b) => b.count - a.count)
      .slice(0, 4);
  }

  onAffinityClick(hub: any): void {
    if (!hub || !hub.key) return;
    this.filterText = hub.key;
    this.onFilterChange();
  }

  locationBars(): { label: string; count: number; pct: number }[] {
    const counts: Record<string, number> = {};
    const total = this.filteredVagas().length || 1;
    this.filteredVagas().forEach(r => {
      const g = this.resolveGeo(r);
      const lbl = g.label || g.countryCode || 'Diversos';
      counts[lbl] = (counts[lbl] || 0) + 1;
    });

    return Object.entries(counts)
      .map(([label, count]) => ({ label, count, pct: Math.round((count / total) * 100) }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 5);
  }

  workplaceBars(): { label: string; count: number; pct: number }[] {
    const counts: Record<string, number> = { 'Remoto': 0, 'Híbrido': 0, 'Presencial': 0, 'Não informado': 0 };
    const total = this.filteredVagas().length || 1;
    this.filteredVagas().forEach(r => {
      const lbl = MODELOS[r.workplace_type || ''] || 'Não informado';
      counts[lbl] = (counts[lbl] || 0) + 1;
    });

    return Object.entries(counts)
      .filter(([_, count]) => count > 0)
      .map(([label, count]) => ({ label, count, pct: Math.round((count / total) * 100) }))
      .sort((a, b) => b.count - a.count);
  }

  portalBars(): { label: string; count: number; pct: number }[] {
    const counts: Record<string, number> = {};
    const total = this.filteredVagas().length || 1;
    this.filteredVagas().forEach(r => {
      const p = this.getPortalName(r.portal);
      counts[p] = (counts[p] || 0) + 1;
    });

    return Object.entries(counts)
      .map(([label, count]) => ({ label, count, pct: Math.round((count / total) * 100) }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 5);
  }

  private updateMap(): void {
    if (!this.geoData) return;

    // Sincronização 100%: o mapa agora usa as mesmas vagas base dos filtros ativos!
    const baseRows = this.getBaseFilteredVagas();
    const brCounts: Record<string, number> = {};
    const worldCounts: Record<string, number> = {};
    const brScores: Record<string, number> = {};
    const worldScores: Record<string, number> = {};
    this.remoteCounts = { REMOTO_BR: 0, EU_REMOTE: 0, GLOBAL_REMOTE: 0 };
    this.remoteScores = { REMOTO_BR: -1, EU_REMOTE: -1, GLOBAL_REMOTE: -1 };

    baseRows.forEach(r => {
      const geo = this.resolveGeo(r);
      const score = (r.screening && typeof r.screening.score === 'number') ? r.screening.score : -1;

      if (geo.remoteBucket) {
        this.remoteCounts[geo.remoteBucket] = (this.remoteCounts[geo.remoteBucket] || 0) + 1;
        if (score > this.remoteScores[geo.remoteBucket]) this.remoteScores[geo.remoteBucket] = score;
      }

      if (geo.countryCode === 'BR') {
        worldCounts['BR'] = (worldCounts['BR'] || 0) + 1;
        if (score > (worldScores['BR'] || -1)) worldScores['BR'] = score;
        if (geo.code && geo.code !== 'REMOTO_BR') {
          brCounts[geo.code] = (brCounts[geo.code] || 0) + 1;
          if (score > (brScores[geo.code] || -1)) brScores[geo.code] = score;
        }
      } else if (geo.countryCode && geo.countryCode !== 'GLOBAL_REMOTE' && geo.countryCode !== 'EU_REMOTE') {
        worldCounts[geo.countryCode] = (worldCounts[geo.countryCode] || 0) + 1;
        if (score > (worldScores[geo.countryCode] || -1)) worldScores[geo.countryCode] = score;
      }
    });

    if (this.mapWorldContainer?.nativeElement) {
      this.renderWorldMapSvg(this.geoData.world || {}, worldCounts, worldScores);
    }
    if (this.mapBrasilContainer?.nativeElement) {
      this.renderBrasilMapSvg(this.geoData.brasil || {}, brCounts, brScores);
    }
  }

  private renderWorldMapSvg(world: Record<string, any>, counts: Record<string, number>, scores: Record<string, number>): void {
    const el = this.mapWorldContainer.nativeElement;
    el.innerHTML = '';

    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 1000 500');
    svg.setAttribute('style', 'width: 100%; height: auto; max-height: 500px; display: block;');

    // Radial gradient background
    const defs = document.createElementNS(SVG_NS, 'defs');
    const grad = document.createElementNS(SVG_NS, 'radialGradient');
    grad.setAttribute('id', 'world-ocean-grad');
    grad.setAttribute('cx', '50%');
    grad.setAttribute('cy', '45%');
    grad.setAttribute('r', '70%');
    grad.innerHTML = `<stop offset="0%" stop-color="#0d1525"/><stop offset="100%" stop-color="#070b13"/>`;
    defs.appendChild(grad);
    svg.appendChild(defs);

    const bgRect = document.createElementNS(SVG_NS, 'rect');
    bgRect.setAttribute('width', '1000');
    bgRect.setAttribute('height', '500');
    bgRect.setAttribute('rx', '10');
    bgRect.setAttribute('fill', 'url(#world-ocean-grad)');
    svg.appendChild(bgRect);

    // Cartographic lines
    const gGrid = document.createElementNS(SVG_NS, 'g');
    gGrid.setAttribute('style', 'pointer-events: none;');
    gGrid.innerHTML = `
      <line x1="20" y1="250" x2="980" y2="250" stroke="rgba(51, 65, 85, 0.28)" stroke-dasharray="4 6"/>
      <line x1="20" y1="180" x2="980" y2="180" stroke="rgba(51, 65, 85, 0.16)" stroke-dasharray="3 6"/>
      <line x1="20" y1="320" x2="980" y2="320" stroke="rgba(51, 65, 85, 0.16)" stroke-dasharray="3 6"/>
      <line x1="250" y1="20" x2="250" y2="480" stroke="rgba(51, 65, 85, 0.16)" stroke-dasharray="3 6"/>
      <line x1="500" y1="20" x2="500" y2="480" stroke="rgba(51, 65, 85, 0.22)" stroke-dasharray="4 6"/>
      <line x1="750" y1="20" x2="750" y2="480" stroke="rgba(51, 65, 85, 0.16)" stroke-dasharray="3 6"/>
    `;
    svg.appendChild(gGrid);

    const gPaths = document.createElementNS(SVG_NS, 'g');
    const gBadges = document.createElementNS(SVG_NS, 'g');

    for (const [code, info] of Object.entries(world)) {
      if (code === 'AQ') continue;
      const cnt = counts[code] || 0;
      const maxScore = scores[code] || -1;
      const isHighFit = this.isTriageMode && maxScore >= 75;
      const isActive = this.activeGeoFilter?.type === 'country' && this.activeGeoFilter.code === code;
      const fill = this.getGeoColor(cnt, maxScore, isActive);

      const path = document.createElementNS(SVG_NS, 'path');
      path.setAttribute('class', `geo-state ${isActive ? 'active' : ''} ${isHighFit ? 'fit-high' : ''}`);
      path.setAttribute('d', info.path);
      path.setAttribute('fill', fill);
      path.setAttribute('data-code', code);
      path.setAttribute('data-name', info.name);

      path.addEventListener('click', () => {
        if (code === 'BR') {
          this.switchMapMode('brasil');
        } else {
          this.activeGeoFilter = { type: 'country', code, name: `${info.name} (${code})`, count: cnt };
          this.onFilterChange();
        }
      });

      gPaths.appendChild(path);

      if (cnt > 0 && info.cx > 0 && info.cy > 0) {
        const gBadge = document.createElementNS(SVG_NS, 'g');
        gBadge.setAttribute('style', 'cursor: pointer;');
        const hasScore = this.isTriageMode && maxScore >= 0;
        const rectW = hasScore ? 62 : 46;

        gBadge.innerHTML = `
          <rect class="geo-badge-bg ${isHighFit ? 'fit-high' : ''}" x="${info.cx - rectW / 2}" y="${info.cy - 12}" width="${rectW}" height="24"/>
          <text class="geo-badge" x="${info.cx}" y="${info.cy - 1}">${code}</text>
          <text class="geo-badge-sub" style="fill: ${isHighFit ? '#34d399' : '#38bdf8'}; font-size: 8.5px;" x="${info.cx}" y="${info.cy + 9}">${hasScore ? `${cnt} (${maxScore}p)` : `${cnt} vaga(s)`}</text>
        `;
        gBadge.addEventListener('click', () => {
          if (code === 'BR') {
            this.switchMapMode('brasil');
          } else {
            this.activeGeoFilter = { type: 'country', code, name: `${info.name} (${code})`, count: cnt };
            this.onFilterChange();
          }
        });
        gBadges.appendChild(gBadge);
      }
    }

    svg.appendChild(gPaths);
    svg.appendChild(gBadges);
    el.appendChild(svg);
  }

  private renderBrasilMapSvg(states: Record<string, any>, counts: Record<string, number>, scores: Record<string, number>): void {
    const el = this.mapBrasilContainer.nativeElement;
    el.innerHTML = '';

    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 600 600');
    svg.setAttribute('style', 'width: 100%; height: auto; max-height: 500px; display: block;');

    const defs = document.createElementNS(SVG_NS, 'defs');
    const grad = document.createElementNS(SVG_NS, 'radialGradient');
    grad.setAttribute('id', 'br-ocean-grad');
    grad.setAttribute('cx', '50%');
    grad.setAttribute('cy', '50%');
    grad.setAttribute('r', '70%');
    grad.innerHTML = `<stop offset="0%" stop-color="#0d1525"/><stop offset="100%" stop-color="#070b13"/>`;
    defs.appendChild(grad);
    svg.appendChild(defs);

    const bgRect = document.createElementNS(SVG_NS, 'rect');
    bgRect.setAttribute('width', '600');
    bgRect.setAttribute('height', '600');
    bgRect.setAttribute('rx', '10');
    bgRect.setAttribute('fill', 'url(#br-ocean-grad)');
    svg.appendChild(bgRect);

    const gPaths = document.createElementNS(SVG_NS, 'g');
    const gBadges = document.createElementNS(SVG_NS, 'g');

    for (const [uf, info] of Object.entries(states)) {
      const cnt = counts[uf] || 0;
      const maxScore = scores[uf] || -1;
      const isHighFit = this.isTriageMode && maxScore >= 75;
      const isActive = this.activeGeoFilter?.type === 'uf' && this.activeGeoFilter.code === uf;
      const fill = this.getGeoColor(cnt, maxScore, isActive);

      const path = document.createElementNS(SVG_NS, 'path');
      path.setAttribute('class', `geo-state ${isActive ? 'active' : ''} ${isHighFit ? 'fit-high' : ''}`);
      path.setAttribute('d', info.path);
      path.setAttribute('fill', fill);
      path.setAttribute('data-uf', uf);
      path.setAttribute('data-name', info.name);

      path.addEventListener('click', () => {
        this.activeGeoFilter = { type: 'uf', code: uf, name: `${info.name} (${uf})`, count: cnt };
        this.onFilterChange();
      });

      gPaths.appendChild(path);

      if (cnt > 0) {
        const gBadge = document.createElementNS(SVG_NS, 'g');
        gBadge.setAttribute('style', 'cursor: pointer;');
        const hasScore = this.isTriageMode && maxScore >= 0;
        const rectW = hasScore ? 62 : 46;

        gBadge.innerHTML = `
          <rect class="geo-badge-bg ${isHighFit ? 'fit-high' : ''}" x="${info.cx - rectW / 2}" y="${info.cy - 12}" width="${rectW}" height="24"/>
          <text class="geo-badge" x="${info.cx}" y="${info.cy - 1}">${uf}</text>
          <text class="geo-badge-sub" style="fill: ${isHighFit ? '#34d399' : '#38bdf8'}; font-size: 8.5px;" x="${info.cx}" y="${info.cy + 9}">${hasScore ? `${cnt} (${maxScore}p)` : `${cnt} vaga(s)`}</text>
        `;
        gBadge.addEventListener('click', () => {
          this.activeGeoFilter = { type: 'uf', code: uf, name: `${info.name} (${uf})`, count: cnt };
          this.onFilterChange();
        });
        gBadges.appendChild(gBadge);
      } else {
        const txtUf = document.createElementNS(SVG_NS, 'text');
        txtUf.setAttribute('class', 'geo-badge-sub');
        txtUf.setAttribute('style', 'fill: #475569; font-size: 8px;');
        txtUf.setAttribute('x', String(info.cx));
        txtUf.setAttribute('y', String(info.cy + 3));
        txtUf.textContent = uf;
        gBadges.appendChild(txtUf);
      }
    }

    svg.appendChild(gPaths);
    svg.appendChild(gBadges);
    el.appendChild(svg);
  }

  private getGeoColor(cnt: number, maxScore: number, isActive: boolean): string {
    if (isActive) return '#38bdf8';
    if (!cnt || cnt <= 0) return '#131b2b';
    if (this.isTriageMode) {
      if (maxScore >= 75) return '#10b981';
      if (maxScore >= 60) return '#0ea5e9';
      return '#64748b';
    }
    if (cnt >= 10) return '#f59e0b';
    if (cnt >= 5) return '#0284c7';
    return '#0369a1';
  }

  resolveGeo(r: Vaga): GeoResolution {
    const rawLoc = String(r.location || '').trim();
    const loc = rawLoc.toLowerCase();
    const portal = String(r.portal || '').toLowerCase();
    const workplace = String(r.workplace_type || '').toLowerCase();
    const isRemote = workplace === 'remote' || loc.includes('remot') || loc.includes('home office') || loc.includes('teletrabalho');
    const hasExplicitBrasil = loc.includes('brasil') || loc.includes('brazil');

    if (!hasExplicitBrasil) {
      for (const country of WORLD_PATTERNS) {
        for (const w of country.words) {
          if (loc.includes(w)) {
            return {
              scope: country.scope as any,
              countryCode: country.code,
              code: country.code,
              label: country.name,
              isRemote,
              remoteBucket: isRemote ? (country.scope === 'europa' ? 'EU_REMOTE' : 'GLOBAL_REMOTE') : null
            };
          }
        }
      }
    }

    if (portal === 'eures') {
      return {
        scope: 'europa',
        countryCode: 'DE',
        code: isRemote ? 'EU_REMOTE' : 'DE',
        label: isRemote ? 'Remoto Europa' : 'Europa (EURES)',
        isRemote,
        remoteBucket: isRemote ? 'EU_REMOTE' : null
      };
    }

    for (const m of BR_UF_WORDS) {
      for (const w of m.words) {
        const regex = new RegExp('(^|[\\s,/()-])' + w + '([\\s,/()-]|$)', 'i');
        if (regex.test(loc)) {
          return {
            scope: 'brasil',
            countryCode: 'BR',
            code: m.uf,
            label: `${m.name} (${m.uf})`,
            isRemote,
            remoteBucket: isRemote ? 'REMOTO_BR' : null
          };
        }
      }
    }

    if (hasExplicitBrasil || BR_PORTALS.has(portal)) {
      return {
        scope: 'brasil',
        countryCode: 'BR',
        code: isRemote ? 'REMOTO_BR' : 'SP',
        label: isRemote ? 'Remoto Brasil' : 'Brasil (Nacional)',
        isRemote,
        remoteBucket: isRemote ? 'REMOTO_BR' : null
      };
    }

    if (isRemote) {
      return {
        scope: 'global',
        countryCode: 'GLOBAL_REMOTE',
        code: 'GLOBAL_REMOTE',
        label: 'Remoto Global',
        isRemote: true,
        remoteBucket: 'GLOBAL_REMOTE'
      };
    }

    return {
      scope: 'brasil',
      countryCode: 'BR',
      code: 'SP',
      label: 'São Paulo (SP)',
      isRemote: false,
      remoteBucket: null
    };
  }

  // --- Ações de Vagas ---
  markInteresse(vaga: Vaga): void {
    this.api.markDecision([vaga.url], 'interesse', vaga).subscribe({
      next: () => {
        this.allVagas.set(this.allVagas().filter(v => v.url !== vaga.url));
        this.api.sessionVagas.set(this.allVagas());
        this.onFilterChange();
      },
      error: (err) => alert('Não consegui salvar: ' + err.message)
    });
  }

  markDescartar(vaga: Vaga): void {
    this.api.markDecision([vaga.url], 'descartar').subscribe({
      next: () => {
        this.allVagas.set(this.allVagas().filter(v => v.url !== vaga.url));
        this.api.sessionVagas.set(this.allVagas());
        this.onFilterChange();
      },
      error: (err) => alert('Não consegui descartar: ' + err.message)
    });
  }

  isAllSelected(): boolean {
    const list = this.filteredVagas();
    return list.length > 0 && list.every(v => this.selectedUrls.has(v.url));
  }

  toggleSelectAll(e: any): void {
    const checked = e.target.checked;
    this.filteredVagas().forEach(v => {
      if (checked) this.selectedUrls.add(v.url);
      else this.selectedUrls.delete(v.url);
    });
  }

  toggleVagaSelection(url: string, e: any): void {
    if (e.target.checked) this.selectedUrls.add(url);
    else this.selectedUrls.delete(url);
  }

  triggerBatchScreen(): void {
    let urls: string[] = [];
    const list = this.filteredVagas().map(v => v.url);
    if (this.batchScope === 'selected') {
      urls = list.filter(u => this.selectedUrls.has(u));
    } else if (this.batchScope === 'all-visible') {
      urls = list;
    } else {
      const n = parseInt(this.batchScope, 10) || 5;
      urls = list.slice(0, n);
    }

    if (!urls.length) {
      alert('Nenhuma vaga selecionada para triagem.');
      return;
    }

    this.batchRunning.set(true);
    this.batchStatus.set(`Iniciando triagem de ${urls.length} vagas…`);

    this.api.startBatchScreen(urls).subscribe({
      next: () => {
        this.pollBatchStatus();
      },
      error: (err) => {
        this.batchRunning.set(false);
        this.batchStatus.set('');
        alert('Erro ao iniciar triagem: ' + err.message);
      }
    });
  }

  private pollBatchStatus(): void {
    const interval = setInterval(() => {
      this.api.getSearchStatus().subscribe({
        next: (st) => {
          const batch = st.batch;
          if (batch && batch.running) {
            this.batchStatus.set(`Triando ${batch.current} de ${batch.total}…`);
          } else {
            clearInterval(interval);
            this.batchRunning.set(false);
            this.batchStatus.set(batch?.total ? `Triagem de ${batch.total} vagas concluída!` : '');
            this.loadResults();
          }
        },
        error: () => {
          clearInterval(interval);
          this.batchRunning.set(false);
        }
      });
    }, 2000);
  }

  clearPendingJobs(): void {
    if (!confirm('Deseja descartar as vagas pendentes não salvas?')) return;
    this.api.clearPending().subscribe({
      next: (res) => {
        alert(`${res.cleared ?? 0} vagas pendentes foram descartadas.`);
        this.loadResults();
      },
      error: (err) => alert('Erro ao limpar vagas: ' + err.message)
    });
  }

  getPortalName(portal?: string): string {
    return portal ? (PORTAIS[portal] || portal.replace(/-search$/, '')) : 'Portal';
  }

  getModelLabel(type?: string): string {
    return type ? (MODELOS[type] || type) : 'Modelo não informado';
  }

  hasVisa(vaga: Vaga): boolean {
    return (vaga as any).visa_sponsorship === true || (vaga as any).visa_sponsorship === 'true' || (vaga as any).visa_sponsorship === 1;
  }

  getWarning(vaga: Vaga): string | null {
    const v = vaga.signals?.warnings?.[0];
    return v ? v.replace(/^posting_signals:\s*/, '').trim() : null;
  }
}
