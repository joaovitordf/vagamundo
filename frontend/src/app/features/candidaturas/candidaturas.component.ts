import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';
import { ApplicationTimelineEvent } from '../../core/models/vaga.model';

const STATUS_LABELS: Record<string, string> = {
  applied: 'Enviada',
  screening: 'Triagem',
  interview: 'Entrevista',
  offer: 'Proposta',
  hired: 'Contratação',
  rejected: 'Não seguiu',
  no_response: 'Sem resposta',
  offer_declined: 'Proposta recusada',
  withdrawn: 'Desistência'
};

@Component({
  selector: 'app-candidaturas',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './candidaturas.component.html',
  styleUrl: './candidaturas.component.css'
})
export class CandidaturasComponent implements OnInit {
  private readonly api = inject(ApiService);
  applications = signal<any[]>([]);
  loading = signal<boolean>(true);

  // Filtros de Data, Status e Busca
  dateCriterion = signal<'applied' | 'posted'>('applied'); // 'applied' = quando candidatei; 'posted' = data da vaga
  dateRange = signal<string>('all'); // 'all', 'today', '3d', '7d', '15d', '30d', 'custom'
  customStartDate = signal<string>('');
  customEndDate = signal<string>('');
  sortOrder = signal<'recent' | 'oldest'>('recent');
  statusFilter = signal<string>('all');
  searchTerm = signal<string>('');

  // Indicador de filtros ativos
  hasActiveFilters = computed(() => {
    return this.dateRange() !== 'all' ||
      this.statusFilter() !== 'all' ||
      this.searchTerm().trim().length > 0 ||
      (this.dateRange() === 'custom' && (!!this.customStartDate() || !!this.customEndDate())) ||
      this.sortOrder() !== 'recent';
  });

  // Lista filtrada e ordenada reativamente
  filteredApplications = computed(() => {
    let list = this.applications();
    const search = this.searchTerm().trim().toLowerCase();
    const statusF = this.statusFilter();
    const criterion = this.dateCriterion();
    const range = this.dateRange();
    const start = this.customStartDate();
    const end = this.customEndDate();
    const order = this.sortOrder();

    // 1. Filtro textual
    if (search) {
      list = list.filter(a =>
        (a.company || a.job_company || '').toLowerCase().includes(search) ||
        (a.role || a.title || a.job_title || '').toLowerCase().includes(search) ||
        (a.channel || a.portal || '').toLowerCase().includes(search) ||
        (a.notes || '').toLowerCase().includes(search)
      );
    }

    // 2. Filtro por status
    if (statusF !== 'all') {
      list = list.filter(a => (a.status || 'applied').toLowerCase() === statusF.toLowerCase());
    }

    // 3. Filtro de data
    if (range !== 'all') {
      const now = new Date();
      now.setHours(23, 59, 59, 999);

      list = list.filter(a => {
        const rawDate = criterion === 'applied'
          ? (a.applied_date || a.date || a.created_at)
          : (a.job_posted_date || a.posted_date || a.date || a.applied_date);

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

    // 4. Ordenação
    return [...list].sort((a, b) => {
      const dateA = criterion === 'applied'
        ? (a.applied_date || a.date || a.created_at || '')
        : (a.job_posted_date || a.posted_date || a.date || a.applied_date || '');
      const dateB = criterion === 'applied'
        ? (b.applied_date || b.date || b.created_at || '')
        : (b.job_posted_date || b.posted_date || b.date || b.applied_date || '');

      const strA = String(dateA).substring(0, 10);
      const strB = String(dateB).substring(0, 10);

      if (order === 'oldest') {
        return strA.localeCompare(strB);
      }
      return strB.localeCompare(strA);
    });
  });

  // Modal de Histórico de Entrevistas
  selectedApp = signal<any | null>(null);
  historyEvents = signal<ApplicationTimelineEvent[]>([]);
  loadingEvents = signal<boolean>(false);
  savingEvent = signal<boolean>(false);
  preparingInterview = signal<string | null>(null);
  generatingDoc = signal<string | null>(null);

  // Campos do formulário de novo evento
  formStage = 'Triagem RH';
  formDate = new Date().toISOString().substring(0, 10);
  formFeedback = '';
  formQuestions = '';
  formStatus = 'interview';

  ngOnInit(): void {
    this.loadApplications();
  }

  loadApplications(): void {
    this.loading.set(true);
    this.api.getApplications().subscribe({
      next: (apps) => {
        this.applications.set(apps || []);
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Erro ao carregar candidaturas:', err);
        this.loading.set(false);
      }
    });
  }

  clearFilters(): void {
    this.dateRange.set('all');
    this.customStartDate.set('');
    this.customEndDate.set('');
    this.searchTerm.set('');
    this.statusFilter.set('all');
    this.sortOrder.set('recent');
  }

  formatDate(d: string): string {
    if (!d) return '-';
    const datePart = String(d).substring(0, 10);
    const parts = datePart.split('-');
    if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
    return d;
  }

  getStatusLabel(s: string): string {
    return STATUS_LABELS[(s || '').toLowerCase()] || s || 'Enviada';
  }

  encodePath(path: string): string {
    return encodeURIComponent(path || '');
  }

  prepareInterview(app: any): void {
    const url = app?.url || app?.job_url || app?.source;
    if (!url) {
      alert('URL da vaga não disponível para preparar entrevista.');
      return;
    }
    this.preparingInterview.set(url);
    this.api.triggerClaude({ url, step: 'entrevista' }).subscribe({
      next: () => {
        this.preparingInterview.set(null);
        this.loadApplications();
        if (this.selectedApp()) {
          // Refresh selected app pdf_entrevista
          this.api.getApplications().subscribe({
            next: (apps) => {
              const updated = apps.find(a => (a.url || a.job_url || a.source) === url);
              if (updated) this.selectedApp.set(updated);
            }
          });
        }
      },
      error: (err) => {
        this.preparingInterview.set(null);
        alert('Erro ao preparar entrevista com IA: ' + (err.error?.detail || err.message));
      }
    });
  }

  generateCarta(app: any): void {
    const url = app?.url || app?.job_url || app?.source;
    if (!url) {
      alert('URL da vaga não disponível para gerar carta de apresentação.');
      return;
    }
    const key = url + '_carta';
    this.generatingDoc.set(key);
    this.api.triggerClaude({ url, step: 'carta' }).subscribe({
      next: () => {
        this.generatingDoc.set(null);
        this.loadApplications();
        if (this.selectedApp()) {
          this.api.getApplications().subscribe({
            next: (apps) => {
              const updated = apps.find(a => (a.url || a.job_url || a.source) === url);
              if (updated) this.selectedApp.set(updated);
            }
          });
        }
      },
      error: (err) => {
        this.generatingDoc.set(null);
        alert('Erro ao gerar carta com IA: ' + (err.error?.detail || err.message));
      }
    });
  }

  generateCv(app: any): void {
    const url = app?.url || app?.job_url || app?.source;
    if (!url) {
      alert('URL da vaga não disponível para gerar currículo.');
      return;
    }
    const key = url + '_cv';
    this.generatingDoc.set(key);
    this.api.triggerClaude({ url, step: 'curriculo' }).subscribe({
      next: () => {
        this.generatingDoc.set(null);
        this.loadApplications();
        if (this.selectedApp()) {
          this.api.getApplications().subscribe({
            next: (apps) => {
              const updated = apps.find(a => (a.url || a.job_url || a.source) === url);
              if (updated) this.selectedApp.set(updated);
            }
          });
        }
      },
      error: (err) => {
        this.generatingDoc.set(null);
        alert('Erro ao gerar currículo com IA: ' + (err.error?.detail || err.message));
      }
    });
  }

  deleteApplication(app: any): void {
    const title = app.role || app.title || app.job_title || 'esta vaga';
    const company = app.company || app.job_company || '';
    const desc = company ? `"${title}" na empresa "${company}"` : `"${title}"`;
    if (!confirm(`Deseja realmente remover a candidatura para ${desc} da sua lista?`)) {
      return;
    }
    const url = app.url || app.source || app.job_url || '';
    const id = app.id;
    const jobId = app.job_id;
    this.api.removeApplication({ url, id, job_id: jobId }).subscribe({
      next: () => {
        this.loadApplications();
      },
      error: (err) => {
        alert('Erro ao remover candidatura: ' + (err.error?.detail || err.message));
      }
    });
  }

  // --- Modal de Histórico de Entrevistas ---
  openHistoryModal(app: any): void {
    this.selectedApp.set(app);
    this.formStage = 'Triagem RH';
    this.formDate = new Date().toISOString().substring(0, 10);
    this.formFeedback = '';
    this.formQuestions = '';
    this.formStatus = app.status || 'interview';
    this.loadEventsForSelected();
  }

  closeHistoryModal(): void {
    this.selectedApp.set(null);
    this.historyEvents.set([]);
  }

  loadEventsForSelected(): void {
    const app = this.selectedApp();
    if (!app || !app.id) {
      this.historyEvents.set([]);
      return;
    }
    this.loadingEvents.set(true);
    this.api.getApplicationEvents(app.id).subscribe({
      next: (res) => {
        this.historyEvents.set(res?.events || []);
        this.loadingEvents.set(false);
      },
      error: (err) => {
        console.error('Erro ao buscar histórico:', err);
        this.loadingEvents.set(false);
      }
    });
  }

  submitNewEvent(): void {
    const app = this.selectedApp();
    if (!app) return;

    if (!this.formStage.trim()) {
      alert('Informe a etapa do processo seletivo.');
      return;
    }

    this.savingEvent.set(true);
    const payload = {
      application_id: app.id,
      job_id: app.job_id,
      url: app.url || app.job_url || app.source,
      stage: this.formStage.trim(),
      event_date: this.formDate,
      feedback: this.formFeedback.trim(),
      questions_and_answers: this.formQuestions.trim(),
      status: this.formStatus
    };

    this.api.addApplicationEvent(payload).subscribe({
      next: () => {
        this.savingEvent.set(false);
        this.formFeedback = '';
        this.formQuestions = '';
        this.loadEventsForSelected();
        this.loadApplications();
      },
      error: (err) => {
        this.savingEvent.set(false);
        alert('Erro ao registrar etapa: ' + (err.error?.detail || err.message));
      }
    });
  }

  deleteEvent(eventId?: number): void {
    if (!eventId) return;
    if (!confirm('Deseja excluir este registro de histórico?')) return;

    this.api.deleteApplicationEvent(eventId).subscribe({
      next: () => {
        this.loadEventsForSelected();
        this.loadApplications();
      },
      error: (err) => {
        alert('Erro ao excluir evento: ' + (err.error?.detail || err.message));
      }
    });
  }
}
