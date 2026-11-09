import { Component, OnInit, inject, signal, computed, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';
import { RecruiterPost } from '../../core/models/vaga.model';

@Component({
  selector: 'app-recrutadores',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './recrutadores.component.html',
  styleUrl: './recrutadores.component.css'
})
export class RecrutadoresComponent implements OnInit {
  private readonly api = inject(ApiService);

  constructor() {
    // Sincroniza a contagem de resultados na sidebar apenas quando houver busca ativa na sessão
    effect(() => {
      const posts = this.filteredPosts();
      if (this.hasSearched()) {
        this.api.hasSearchedRecruitersInSession.set(true);
        this.api.recruiterPostsCount.set(posts.length);
      } else {
        this.api.hasSearchedRecruitersInSession.set(false);
        this.api.recruiterPostsCount.set(0);
      }
    });
  }

  // Estados principais
  readonly allPosts = signal<RecruiterPost[]>([]);
  readonly loading = signal<boolean>(false);
  readonly hasSearched = signal<boolean>(false);
  readonly statusMessage = signal<string>('');
  readonly errorMessage = signal<string>('');
  readonly copiedEmail = signal<string | null>(null);

  // Filtros
  filterText = '';
  onlyCvMatch = signal<boolean>(false);
  portalFilter = '';
  cvAreaBadge = signal<string>('');

  // Sorteador de CV
  private cvAreasList: any[] = [];
  private cvAreaQueue: any[] = [];
  private lastPickedAreaId: string | null = null;

  // Controle de expansão de texto completo por card (ID -> boolean)
  expandedPosts = signal<Set<number>>(new Set());

  // Lista dinâmica de portais encontrados nos dados
  readonly availablePortals = computed(() => {
    const set = new Set<string>();
    for (const p of this.allPosts()) {
      if (p.portal) set.add(p.portal);
    }
    return Array.from(set).sort();
  });

  // Lista filtrada computada (só exibe resultados após pesquisa com palavras-chave)
  readonly filteredPosts = computed(() => {
    if (!this.hasSearched()) {
      return [];
    }

    const query = this.filterText.trim().toLowerCase();
    if (!query) {
      return [];
    }

    let posts = this.allPosts();
    const onlyCv = this.onlyCvMatch();
    const portal = this.portalFilter;

    if (onlyCv) {
      posts = posts.filter(p => (p.matched_keywords && p.matched_keywords.length > 0) || (p.match_score && p.match_score > 0));
    }

    if (portal) {
      posts = posts.filter(p => p.portal === portal);
    }

    const terms = query.split(',').map(t => t.trim().toLowerCase()).filter(Boolean);
    if (terms.length > 0) {
      posts = posts.filter(p => {
        const hay = `${p.title || ''} ${p.company || ''} ${p.description || ''} ${(p.emails || []).join(' ')} ${(p.matched_keywords || []).join(' ')}`.toLowerCase();
        return terms.some(t => hay.includes(t));
      });
    }

    return posts;
  });

  ngOnInit(): void {
    // Não carrega posts automaticamente: aguarda o usuário digitar termos e clicar em Buscar
    this.loadCvAreas();
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

  onSearch(): void {
    const term = (this.filterText || '').trim();
    if (!term) {
      this.errorMessage.set('Por favor, digite pelo menos uma palavra-chave (ex: tecnologia ou cargo) ou clique em "Sortear área CV" antes de buscar.');
      return;
    }

    this.hasSearched.set(true);
    this.loading.set(true);
    this.errorMessage.set('');
    this.statusMessage.set('');

    // Sincroniza da base local e threads públicas (como Hacker News) para os termos
    this.api.syncRecruiterPosts(term).subscribe({
      next: (res) => {
        if (res && res.hn_synced && res.hn_synced > 0) {
          this.statusMessage.set(`${res.hn_synced} novo(s) contato(s) obtido(s) do Hacker News Who is Hiring!`);
        }
        this.fetchPosts();
      },
      error: () => {
        this.fetchPosts();
      }
    });
  }

  private fetchPosts(): void {
    this.api.getRecruiterPosts().subscribe({
      next: (res) => {
        this.allPosts.set(res.posts || []);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.errorMessage.set('Erro ao carregar publicações: ' + (err?.error?.detail || err?.message || 'Falha na comunicação'));
      }
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

    const keywords = (picked.keywords || []).slice(0, 3);
    this.filterText = keywords.join(', ');
    this.cvAreaBadge.set(`Área CV: ${picked.label || picked.title}`);
    this.errorMessage.set('');
  }

  clearTextFilter(): void {
    this.filterText = '';
    this.cvAreaBadge.set('');
    this.hasSearched.set(false);
    this.errorMessage.set('');
    this.statusMessage.set('');
  }

  openLinkedInContentSearch(): void {
    const term = (this.filterText || '').trim();
    const queryPart = term ? `(${term.split(',').map(t => `"${t.trim()}"`).join(' OR ')})` : '';
    const emailKeywords = '("envie seu currículo" OR "enviar currículo" OR "mande seu cv" OR "email" OR "send your resume")';
    const fullKeywords = queryPart ? `${queryPart} ${emailKeywords}` : emailKeywords;

    const url = `https://www.linkedin.com/search/results/content/?keywords=${encodeURIComponent(fullKeywords)}&sortBy=%22date_posted%22`;
    window.open(url, '_blank', 'noopener,noreferrer');
  }

  dismissPost(postId: number): void {
    this.api.dismissRecruiterPost(postId).subscribe({
      next: () => {
        this.allPosts.update(posts => posts.filter(p => p.id !== postId));
      },
      error: (err) => {
        this.errorMessage.set('Erro ao remover publicação: ' + (err?.error?.detail || err?.message || 'Falha'));
      }
    });
  }

  copyEmail(email: string): void {
    if (!email) return;
    navigator.clipboard.writeText(email).then(() => {
      this.copiedEmail.set(email);
      setTimeout(() => {
        if (this.copiedEmail() === email) {
          this.copiedEmail.set(null);
        }
      }, 2500);
    }).catch(() => {
      this.copiedEmail.set(email);
      setTimeout(() => this.copiedEmail.set(null), 2500);
    });
  }

  toggleExpand(postId: number): void {
    this.expandedPosts.update(set => {
      const next = new Set(set);
      if (next.has(postId)) {
        next.delete(postId);
      } else {
        next.add(postId);
      }
      return next;
    });
  }

  isExpanded(postId: number): boolean {
    return this.expandedPosts().has(postId);
  }

  getPortalLabel(portal: string): string {
    const map: Record<string, string> = {
      'linkedin_post': 'LinkedIn (Post)',
      'linkedin-search': 'LinkedIn (Vaga)',
      'hn-search': 'Hacker News (Who is Hiring)',
      'remotar-search': 'Remotar',
      'freehire-search': 'FreeHire',
      'gupy-search': 'Gupy',
      'vagas-search': 'Vagas.com',
      'infojobs-search': 'InfoJobs',
      'programathor-search': 'Programathor',
      'geekhunter-search': 'GeekHunter',
      'trampos-search': 'Trampos',
      'jobs': 'Banco Local de Vagas',
    };
    return map[portal] || portal.replace('-search', '').toUpperCase();
  }

  getPortalOriginInfo(post: RecruiterPost): string {
    if (post.portal === 'linkedin_post') {
      return 'Publicação colada do feed do LinkedIn';
    }
    if (post.portal === 'hn-search') {
      return 'Thread "Who is Hiring" do Hacker News';
    }
    const label = this.getPortalLabel(post.portal);
    return `Vaga do portal ${label} (e-mail de contato direto minerado da descrição)`;
  }
}
