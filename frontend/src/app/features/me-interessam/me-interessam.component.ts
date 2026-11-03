import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';

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

@Component({
  selector: 'app-me-interessam',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './me-interessam.component.html',
  styleUrl: './me-interessam.component.css'
})
export class MeInteressamComponent implements OnInit {
  private readonly api = inject(ApiService);

  savedJobs = signal<any[]>([]);
  loading = signal<boolean>(true);
  actionStatus = signal<string>('');

  // Filtros de Data e Busca
  dateCriterion = signal<'saved' | 'posted'>('saved'); // 'saved' = quando adicionei; 'posted' = data da vaga
  dateRange = signal<string>('all'); // 'all', 'today', '3d', '7d', '15d', '30d', 'custom'
  customStartDate = signal<string>('');
  customEndDate = signal<string>('');
  sortOrder = signal<'recent' | 'oldest' | 'score'>('recent');
  searchTerm = signal<string>('');

  // Indicador de filtros ativos
  hasActiveFilters = computed(() => {
    return this.dateRange() !== 'all' ||
      this.searchTerm().trim().length > 0 ||
      (this.dateRange() === 'custom' && (!!this.customStartDate() || !!this.customEndDate())) ||
      this.sortOrder() !== 'recent';
  });

  // Lista filtrada e ordenada reativamente
  filteredJobs = computed(() => {
    let list = this.savedJobs();
    const search = this.searchTerm().trim().toLowerCase();
    const criterion = this.dateCriterion();
    const range = this.dateRange();
    const start = this.customStartDate();
    const end = this.customEndDate();
    const order = this.sortOrder();

    // 1. Filtro textual
    if (search) {
      list = list.filter(j =>
        (j.title || '').toLowerCase().includes(search) ||
        (j.company || '').toLowerCase().includes(search) ||
        (j.location || '').toLowerCase().includes(search) ||
        (j.portal || '').toLowerCase().includes(search)
      );
    }

    // 2. Filtro de data
    if (range !== 'all') {
      const now = new Date();
      now.setHours(23, 59, 59, 999);

      list = list.filter(j => {
        const rawDate = criterion === 'saved'
          ? (j.saved_at || j.updated_at || j.created_at || j.first_seen || j.date || j.posted_date)
          : (j.posted_date || j.date || j.first_seen);

        if (!rawDate) return false;
        const dateStr = String(rawDate).substring(0, 10);
        const itemDate = new Date(dateStr + 'T12:00:00');
        if (isNaN(itemDate.getTime())) return false;

        if (range === 'custom') {
          if (start && dateStr < start) return false;
          if (end && dateStr > end) return false;
          return true;
        }

        const days = range === 'today' ? 1 : (range === '3d' ? 3 : (range === '7d' ? 7 : (range === '15d' ? 15 : 30)));
        const cutoff = new Date(now.getTime() - days * 24 * 60 * 60 * 1000);
        cutoff.setHours(0, 0, 0, 0);

        return itemDate >= cutoff;
      });
    }

    // 3. Ordenação
    return [...list].sort((a, b) => {
      if (order === 'score') {
        const scA = a.screening?.score ?? -1;
        const scB = b.screening?.score ?? -1;
        if (scB !== scA) return scB - scA;
      }

      const dateA = criterion === 'saved'
        ? (a.saved_at || a.updated_at || a.created_at || a.first_seen || a.date || a.posted_date || '')
        : (a.posted_date || a.date || a.first_seen || '');
      const dateB = criterion === 'saved'
        ? (b.saved_at || b.updated_at || b.created_at || b.first_seen || b.date || b.posted_date || '')
        : (b.posted_date || b.date || b.first_seen || '');

      const strA = String(dateA).substring(0, 10);
      const strB = String(dateB).substring(0, 10);

      if (order === 'oldest') {
        return strA.localeCompare(strB);
      }
      return strB.localeCompare(strA);
    });
  });

  hasDoc(job: any, type: 'avaliar' | 'curriculo' | 'carta' | 'entrevista'): boolean {
    if (!job) return false;
    if (type === 'avaliar') return !!(job.claude && job.claude.avaliar || job.screening);
    if (type === 'curriculo') return !!(job.claude && job.claude.curriculo || job.pdf_cv);
    if (type === 'carta') return !!(job.claude && job.claude.carta || job.pdf_carta);
    if (type === 'entrevista') return !!(job.claude && job.claude.entrevista || job.pdf_entrevista);
    return false;
  }

  ngOnInit(): void {
    this.loadSaved();
  }

  loadSaved(): void {
    this.loading.set(true);
    this.api.getSaved().subscribe({
      next: (jobs) => {
        this.savedJobs.set(jobs || []);
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Erro ao carregar vagas salvas:', err);
        this.loading.set(false);
      }
    });
  }

  clearFilters(): void {
    this.dateRange.set('all');
    this.customStartDate.set('');
    this.customEndDate.set('');
    this.searchTerm.set('');
    this.sortOrder.set('recent');
  }

  formatDateDisplay(d?: string): string {
    if (!d) return '-';
    const datePart = String(d).substring(0, 10);
    const parts = datePart.split('-');
    if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
    return d;
  }

  getPortalName(portal?: string): string {
    return portal ? (PORTAIS[portal] || portal.replace(/-search$/, '')) : 'Portal';
  }

  encodePath(path: string): string {
    return encodeURIComponent(path || '');
  }

  runAi(job: any, step: string): void {
    let label = 'Ação de IA';
    if (step === 'avaliar') label = 'Avaliação rápida';
    else if (step === 'curriculo') label = 'Currículo em PDF';
    else if (step === 'carta') label = 'Carta de Apresentação';
    else if (step === 'entrevista') label = 'Dossiê de Preparação para Entrevista';

    this.actionStatus.set(`A IA está gerando ${label} para "${job.title || 'a vaga'}"… Aguarde.`);
    this.api.triggerClaude({ url: job.url, step }).subscribe({
      next: () => {
        this.actionStatus.set('');
        this.loadSaved();
      },
      error: (err) => {
        this.actionStatus.set('');
        alert('Erro ao processar com IA: ' + (err.error?.detail || err.message));
      }
    });
  }

  markApplied(job: any): void {
    this.actionStatus.set(`Registrando candidatura para "${job.title || 'vaga'}"…`);
    this.api.markApplied({
      url: job.url,
      company: job.company,
      role: job.title || job.role,
      portal: job.portal,
    }).subscribe({
      next: () => {
        this.actionStatus.set('');
        this.loadSaved();
      },
      error: (err) => {
        this.actionStatus.set('');
        alert('Erro ao registrar candidatura: ' + (err.error?.detail || err.message));
      }
    });
  }

  discardJob(job: any): void {
    this.api.discardJob(job.url).subscribe({
      next: () => this.loadSaved(),
      error: (err) => alert('Erro ao descartar: ' + (err.error?.detail || err.message))
    });
  }
}
