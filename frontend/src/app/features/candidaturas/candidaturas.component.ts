import { Component, DestroyRef, OnDestroy, OnInit, inject, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';
import { ToastService } from '../../core/services/toast.service';
import { ApplicationRecord, ApplicationTimelineEvent } from '../../core/models/vaga.model';
import { PortalBadgeComponent } from '../../shared/components/portal-badge.component';
import {
  formatDisplayDate,
  getPortalDisplayName,
  getPrimaryEmail as pickPrimaryEmail,
  isWithinDateRange,
  matchesTextFilter,
  parseCalendarDateMs,
  resolveGeo,
} from '../../core/utils/job-filters.util';

export interface ApplicationsFilterOptions {
  searchTerm: string;
  statusFilter: string;
  channelFilter: 'all' | 'recruiter_email' | 'portal';
  dateCriterion: 'applied' | 'posted';
  dateRange: string;
  customStartDate: string;
  customEndDate: string;
  sortOrder: 'recent' | 'oldest';
}

export function isDirectEmailApplication(app: any): boolean {
  return Boolean(
    app?.contact_channel === 'recruiter_email' ||
    (app?.contacted_email && String(app.contacted_email).trim()) ||
    String(app?.url || app?.job_url || app?.source || '').startsWith('recruiter://')
  );
}

export function filterApplicationsList(applications: any[], opts: ApplicationsFilterOptions): any[] {
  let list = applications;
  const search = opts.searchTerm.trim();
  const statusF = opts.statusFilter;
  const channelF = opts.channelFilter;
  const criterion = opts.dateCriterion;
  const range = opts.dateRange;
  const start = opts.customStartDate;
  const end = opts.customEndDate;
  const order = opts.sortOrder;

  if (search) {
    list = list.filter(a => {
      const emailsText = Array.isArray(a.recruiter_emails) ? a.recruiter_emails.join(' ') : '';
      const portalLabel = getPortalDisplayName(a.channel || a.portal || '');
      const geo = resolveGeo({
        location: a.location || a.job_location,
        portal: a.channel || a.portal,
        title: a.role || a.title || a.job_title,
      });
      const hay = `${a.company || a.job_company || ''} ${a.role || a.title || a.job_title || ''} ${a.location || a.job_location || ''} ${geo.label || ''} ${a.channel || a.portal || ''} ${portalLabel} ${a.notes || ''} ${a.contacted_email || ''} ${emailsText}`;
      return matchesTextFilter(hay, search);
    });
  }

  if (statusF !== 'all') {
    list = list.filter(a => (a.status || 'applied').toLowerCase() === statusF.toLowerCase());
  }

  if (channelF === 'recruiter_email') {
    list = list.filter(a => isDirectEmailApplication(a));
  } else if (channelF === 'portal') {
    list = list.filter(a => !isDirectEmailApplication(a));
  }

  if (range !== 'all') {
    list = list.filter(a => {
      const rawDate = criterion === 'applied'
        ? (a.applied_date || a.date || a.created_at)
        : (a.job_posted_date || a.posted_date || a.date || a.applied_date);
      return isWithinDateRange(rawDate, range, start, end);
    });
  }

  return [...list].sort((a, b) => {
    const dateA = criterion === 'applied'
      ? (a.applied_date || a.date || a.created_at || '')
      : (a.job_posted_date || a.posted_date || a.date || a.applied_date || '');
    const dateB = criterion === 'applied'
      ? (b.applied_date || b.date || b.created_at || '')
      : (b.job_posted_date || b.posted_date || b.date || b.applied_date || '');

    const msA = parseCalendarDateMs(dateA);
    const msB = parseCalendarDateMs(dateB);
    if (msA === null && msB === null) return 0;
    if (msA === null) return 1;
    if (msB === null) return -1;

    if (order === 'oldest') {
      return msA - msB;
    }
    return msB - msA;
  });
}

export const APPLICATION_STATUS_LABELS: Record<string, string> = {
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

export const APPLICATION_STATUS_OPTIONS = Object.entries(APPLICATION_STATUS_LABELS).map(([value, label]) => ({
  value,
  label,
}));

@Component({
  selector: 'app-candidaturas',
  standalone: true,
  imports: [CommonModule, FormsModule, PortalBadgeComponent],
  templateUrl: './candidaturas.component.html',
  styleUrl: './candidaturas.component.css'
})
export class CandidaturasComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);
  private copyEmailTimer: ReturnType<typeof setTimeout> | null = null;
  readonly statusOptions = APPLICATION_STATUS_OPTIONS;
  applications = signal<ApplicationRecord[]>([]);
  loading = signal<boolean>(true);

  // Filtros de Data, Status e Busca
  dateCriterion = signal<'applied' | 'posted'>('applied'); // 'applied' = quando candidatei; 'posted' = data da vaga
  dateRange = signal<string>('all'); // 'all', 'today', '3d', '7d', '15d', '30d', 'custom'
  customStartDate = signal<string>('');
  customEndDate = signal<string>('');
  sortOrder = signal<'recent' | 'oldest'>('recent');
  statusFilter = signal<string>('all');
  channelFilter = signal<'all' | 'recruiter_email' | 'portal'>('all');
  searchTerm = signal<string>('');
  copiedEmail = signal<string | null>(null);
  reopeningKey = signal<string | number | null>(null);
  showModalPostText = signal<boolean>(false);

  // Indicador de filtros ativos
  hasActiveFilters = computed(() => {
    return this.dateRange() !== 'all' ||
      this.statusFilter() !== 'all' ||
      this.channelFilter() !== 'all' ||
      this.searchTerm().trim().length > 0 ||
      (this.dateRange() === 'custom' && (!!this.customStartDate() || !!this.customEndDate())) ||
      this.sortOrder() !== 'recent';
  });

  // Lista filtrada e ordenada reativamente
  filteredApplications = computed(() =>
    filterApplicationsList(this.applications(), {
      searchTerm: this.searchTerm(),
      statusFilter: this.statusFilter(),
      channelFilter: this.channelFilter(),
      dateCriterion: this.dateCriterion(),
      dateRange: this.dateRange(),
      customStartDate: this.customStartDate(),
      customEndDate: this.customEndDate(),
      sortOrder: this.sortOrder(),
    })
  );

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

  ngOnDestroy(): void {
    if (this.copyEmailTimer) {
      clearTimeout(this.copyEmailTimer);
      this.copyEmailTimer = null;
    }
  }

  loadApplications(): void {
    this.loading.set(true);
    this.api.getApplications().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (apps) => {
        this.applications.set(apps || []);
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Erro ao carregar candidaturas:', err);
        this.loading.set(false);
        this.toast.error('Não foi possível carregar as candidaturas.');
      }
    });
  }

  clearFilters(): void {
    this.dateRange.set('all');
    this.customStartDate.set('');
    this.customEndDate.set('');
    this.searchTerm.set('');
    this.statusFilter.set('all');
    this.channelFilter.set('all');
    this.sortOrder.set('recent');
  }

  getPortalLabel(portal?: string): string {
    return getPortalDisplayName(portal);
  }

  getChannelFilterLabel(channel: 'all' | 'recruiter_email' | 'portal'): string {
    if (channel === 'recruiter_email') return 'E-mail direto';
    if (channel === 'portal') return 'Somente portais';
    return 'Todos os canais';
  }

  isHttpUrl(url?: string): boolean {
    return Boolean(url && /^https?:\/\//i.test(String(url).trim()));
  }

  isRecruiterApplication(app: any): boolean {
    return Boolean(app?.recruiter_post_id || isDirectEmailApplication(app));
  }

  getPrimaryEmail(app: any): string | null {
    return pickPrimaryEmail(app);
  }

  copyRecruiterEmail(email: string): void {
    if (!email) return;
    const done = () => {
      this.copiedEmail.set(email);
      if (this.copyEmailTimer) {
        clearTimeout(this.copyEmailTimer);
      }
      this.copyEmailTimer = setTimeout(() => {
        this.copyEmailTimer = null;
        if (this.copiedEmail() === email) {
          this.copiedEmail.set(null);
        }
      }, 2200);
    };
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(email).then(done).catch(done);
    } else {
      done();
    }
  }

  reopenInRecruiters(app: any): void {
    const title = app.role || app.title || app.job_title || 'esta oportunidade';
    const company = app.company || app.job_company || '';
    const desc = company ? `"${title}" (${company})` : `"${title}"`;
    if (!confirm(`Deseja desfazer o registro de ${desc} e devolvê-la para a aba Recrutadores?`)) {
      return;
    }

    const key = app.url || app.job_url || app.id || title;
    this.reopeningKey.set(key);
    this.api.reopenRecruiterApplication({
      id: app.id,
      job_id: app.job_id,
      url: app.url || app.job_url || app.source,
      recruiter_post_id: app.recruiter_post_id,
    }).subscribe({
      next: () => {
        this.reopeningKey.set(null);
        if (this.selectedApp()?.id === app.id) {
          this.closeHistoryModal();
        }
        this.toast.success('Oportunidade devolvida para a aba Recrutadores.');
        this.loadApplications();
      },
      error: (err) => {
        this.reopeningKey.set(null);
        this.toast.error('Erro ao reabrir em Recrutadores: ' + (err.error?.detail || err.message));
      }
    });
  }

  formatDate(d: string): string {
    return d ? formatDisplayDate(d) : '-';
  }

  getStatusLabel(s: string): string {
    return APPLICATION_STATUS_LABELS[(s || '').toLowerCase()] || s || 'Enviada';
  }

  encodePath(path: string): string {
    return encodeURIComponent(path || '');
  }

  private runAiStepForApp(
    app: any,
    step: 'entrevista' | 'carta' | 'curriculo',
    busySignal: { set(val: string | null): void },
    busyKey: (url: string) => string,
    missingUrlMsg: string,
    errorPrefix: string,
    successMsg: string
  ): void {
    const url = app?.url || app?.job_url || app?.source;
    if (!url) {
      this.toast.warning(missingUrlMsg);
      return;
    }
    busySignal.set(busyKey(url));
    this.api.triggerClaude({ url, step }).subscribe({
      next: () => {
        busySignal.set(null);
        this.toast.success(successMsg);
        this.loadApplications();
        if (this.selectedApp()) {
          this.api.getApplications().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (apps) => {
              const updated = apps.find(a => (a.url || a.job_url || a.source) === url);
              if (updated) this.selectedApp.set(updated);
            },
            error: (err) => console.warn('Falha ao atualizar detalhe selecionado:', err),
          });
        }
      },
      error: (err) => {
        busySignal.set(null);
        this.toast.error(errorPrefix + (err.error?.detail || err.message));
      }
    });
  }

  prepareInterview(app: any): void {
    this.runAiStepForApp(
      app,
      'entrevista',
      this.preparingInterview,
      url => url,
      'URL da vaga não disponível para preparar entrevista.',
      'Erro ao preparar entrevista com IA: ',
      'Dossiê de entrevista gerado com sucesso.'
    );
  }

  generateCarta(app: any): void {
    this.runAiStepForApp(
      app,
      'carta',
      this.generatingDoc,
      url => `${url}_carta`,
      'URL da vaga não disponível para gerar carta de apresentação.',
      'Erro ao gerar carta com IA: ',
      'Carta de apresentação gerada com sucesso.'
    );
  }

  generateCv(app: any): void {
    this.runAiStepForApp(
      app,
      'curriculo',
      this.generatingDoc,
      url => `${url}_cv`,
      'URL da vaga não disponível para gerar currículo.',
      'Erro ao gerar currículo com IA: ',
      'Currículo personalizado gerado com sucesso.'
    );
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
        this.toast.success('Candidatura removida da lista.');
        this.loadApplications();
      },
      error: (err) => {
        this.toast.error('Erro ao remover candidatura: ' + (err.error?.detail || err.message));
      }
    });
  }

  // --- Modal de Histórico de Entrevistas ---
  openHistoryModal(app: any): void {
    this.selectedApp.set(app);
    this.showModalPostText.set(false);
    this.formStage = 'Triagem RH';
    this.formDate = new Date().toISOString().substring(0, 10);
    this.formFeedback = '';
    this.formQuestions = '';
    this.formStatus = app.status || 'interview';
    this.loadEventsForSelected();
  }

  closeHistoryModal(): void {
    this.selectedApp.set(null);
    this.showModalPostText.set(false);
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
        this.toast.error('Erro ao buscar histórico de etapas.');
      }
    });
  }

  submitNewEvent(): void {
    const app = this.selectedApp();
    if (!app) return;

    if (!this.formStage.trim()) {
      this.toast.warning('Informe a etapa do processo seletivo.');
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
        this.toast.success('Etapa registrada no histórico.');
        this.loadEventsForSelected();
        this.loadApplications();
      },
      error: (err) => {
        this.savingEvent.set(false);
        this.toast.error('Erro ao registrar etapa: ' + (err.error?.detail || err.message));
      }
    });
  }

  deleteEvent(eventId?: number): void {
    if (!eventId) return;
    if (!confirm('Deseja excluir este registro de histórico?')) return;

    this.api.deleteApplicationEvent(eventId).subscribe({
      next: () => {
        this.toast.success('Registro de histórico excluído.');
        this.loadEventsForSelected();
        this.loadApplications();
      },
      error: (err) => {
        this.toast.error('Erro ao excluir evento: ' + (err.error?.detail || err.message));
      }
    });
  }
}
