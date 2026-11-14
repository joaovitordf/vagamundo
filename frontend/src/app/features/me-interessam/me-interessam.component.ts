import { Component, DestroyRef, OnDestroy, OnInit, inject, signal, computed, effect } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';
import { AutoModeService } from '../../core/services/auto-mode.service';
import { ToastService } from '../../core/services/toast.service';
import { Vaga } from '../../core/models/vaga.model';
import {
  getPortalDisplayName,
  getWorkModelLabel,
  isWithinDateRange,
  matchesTextFilter,
  parseCalendarDateMs,
  resolveEffectiveWorkModel,
  resolveGeo,
} from '../../core/utils/job-filters.util';
import { JobBadgesComponent } from '../../shared/components/job-badges.component';
import { PortalBadgeComponent } from '../../shared/components/portal-badge.component';

@Component({
  selector: 'app-me-interessam',
  standalone: true,
  imports: [CommonModule, FormsModule, JobBadgesComponent, PortalBadgeComponent],
  templateUrl: './me-interessam.component.html',
  styleUrl: './me-interessam.component.css'
})
export class MeInteressamComponent implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly autoMode = inject(AutoModeService);
  private readonly toast = inject(ToastService);

  savedJobs = signal<Vaga[]>([]);
  loading = signal<boolean>(true);
  actionStatus = signal<string>('');
  copiedRecruiterEmail = signal<string | null>(null);

  // Seleção em lote
  selectedUrls = signal<Set<string>>(new Set());
  bulkActionLoading = signal<boolean>(false);
  bulkStatusMsg = signal<string>('');
  reevalRunning = signal<boolean>(false);
  reevalCurrent = signal<number>(0);
  reevalTotal = signal<number>(0);
  reevalPercent = signal<number>(0);
  reevalCurrentTitle = signal<string>('');
  reevalErrors = signal<number>(0);
  reevalProvider = signal<string>('');
  readonly bulkBusy = computed(() => this.reevalRunning() || this.bulkActionLoading());

  // Filtros de Data e Busca
  dateCriterion = signal<'saved' | 'posted'>('saved'); // 'saved' = quando adicionei; 'posted' = data da vaga
  dateRange = signal<string>('all'); // 'all', 'today', '3d', '7d', '15d', '30d', 'custom'
  customStartDate = signal<string>('');
  customEndDate = signal<string>('');
  sortOrder = signal<'recent' | 'oldest' | 'score'>('recent');
  searchTerm = signal<string>('');
  onlyAuto = signal<boolean>(false);
  portalFilter = signal<string>('all');

  private lastSeenAutoTick = 0;
  private reevalPollInterval: any = null;
  private reevalPollInFlight = false;
  private copyTimer: ReturnType<typeof setTimeout> | null = null;
  private lastReevalCount = 0;

  constructor() {
    effect(() => {
      const tick = this.autoMode.resultsRefreshTick();
      if (tick > 0 && tick !== this.lastSeenAutoTick) {
        this.lastSeenAutoTick = tick;
        this.loadSaved(false);
      }
    });
  }

  availablePortals = computed(() => {
    const set = new Set<string>();
    for (const job of this.savedJobs()) {
      const p = (job.portal || '').trim();
      if (p) set.add(p);
    }
    return Array.from(set).sort((a, b) =>
      getPortalDisplayName(a).localeCompare(getPortalDisplayName(b), 'pt-BR')
    );
  });

  // Indicador de filtros ativos
  hasActiveFilters = computed(() => {
    return this.dateRange() !== 'all' ||
      this.searchTerm().trim().length > 0 ||
      this.onlyAuto() ||
      this.portalFilter() !== 'all' ||
      (this.dateRange() === 'custom' && (!!this.customStartDate() || !!this.customEndDate())) ||
      this.sortOrder() !== 'recent';
  });

  // Lista filtrada e ordenada reativamente
  filteredJobs = computed(() => {
    let list = this.savedJobs();
    const search = this.searchTerm().trim();
    const criterion = this.dateCriterion();
    const range = this.dateRange();
    const start = this.customStartDate();
    const end = this.customEndDate();
    const order = this.sortOrder();
    const filterAuto = this.onlyAuto();
    const portalF = this.portalFilter();

    if (filterAuto) {
      list = list.filter(j => Boolean(j.auto_promoted));
    }

    if (portalF !== 'all') {
      list = list.filter(j => (j.portal || '').trim() === portalF);
    }

    // 1. Filtro textual
    if (search) {
      list = list.filter(j => {
        const geo = resolveGeo(j);
        const effModel = resolveEffectiveWorkModel(j);
        const emailsText = Array.isArray(j.recruiter_emails) ? j.recruiter_emails.join(' ') : '';
        const tags = Array.isArray(j.tags) ? j.tags.join(' ') : '';
        const skills = Array.isArray(j.skills) ? j.skills.join(' ') : '';
        const hay = `${j.title || ''} ${j.company || ''} ${j.location || ''} ${geo.label || ''} ${j.portal || ''} ${getPortalDisplayName(j.portal)} ${j.workplace_type || ''} ${getWorkModelLabel(effModel)} ${emailsText} ${tags} ${skills}`;
        return matchesTextFilter(hay, search);
      });
    }

    // 2. Filtro de data
    if (range !== 'all') {
      list = list.filter(j => {
        const rawDate = criterion === 'saved'
          ? (j.saved_at || j.updated_at || j.created_at || j.first_seen || j.date || j.posted_date)
          : (j.posted_date || j.date || j.first_seen);
        return isWithinDateRange(rawDate, range, start, end);
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
  });

  visibleSelectedJobs = computed(() => {
    const sel = this.selectedUrls();
    return this.filteredJobs().filter(j => !!j?.url && sel.has(j.url));
  });

  selectedVisibleCount = computed(() => this.visibleSelectedJobs().length);

  isAllVisibleSelected = computed(() => {
    const list = this.filteredJobs();
    const sel = this.selectedUrls();
    return list.length > 0 && list.every(j => !!j?.url && sel.has(j.url));
  });

  hasDoc(job: Vaga, type: 'avaliar' | 'curriculo' | 'carta' | 'entrevista'): boolean {
    if (!job) return false;
    if (type === 'avaliar') return !!(job.claude && job.claude.avaliar || job.screening);
    if (type === 'curriculo') return !!(job.claude && job.claude.curriculo || job.pdf_cv);
    if (type === 'carta') return !!(job.claude && job.claude.carta || job.pdf_carta);
    if (type === 'entrevista') return !!(job.claude && job.claude.entrevista || job.pdf_entrevista);
    return false;
  }

  ngOnInit(): void {
    this.loadSaved();
    this.checkInitialReevalStatus();
  }

  ngOnDestroy(): void {
    this.cleanupReevalPolling();
    if (this.copyTimer) {
      clearTimeout(this.copyTimer);
      this.copyTimer = null;
    }
  }

  private cleanupReevalPolling(): void {
    if (this.reevalPollInterval) {
      clearInterval(this.reevalPollInterval);
      this.reevalPollInterval = null;
    }
    this.reevalPollInFlight = false;
  }

  loadSaved(showLoader = true): void {
    if (showLoader) {
      this.loading.set(true);
    }
    this.api.getSaved().subscribe({
      next: (jobs) => {
        const list = jobs || [];
        this.savedJobs.set(list);
        this.pruneSelection(list);
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Erro ao carregar vagas salvas:', err);
        this.loading.set(false);
      }
    });
  }

  private pruneSelection(jobs: Vaga[]): void {
    const available = new Set(jobs.map(j => j?.url).filter(Boolean));
    const current = this.selectedUrls();
    let changed = false;
    const next = new Set<string>();
    for (const url of current) {
      if (available.has(url)) {
        next.add(url);
      } else {
        changed = true;
      }
    }
    if (changed) {
      this.selectedUrls.set(next);
    }
  }

  isSelected(url?: string): boolean {
    return !!url && this.selectedUrls().has(url);
  }

  toggleJobSelection(url: string, event?: Event): void {
    if (!url) return;
    const target = event?.target as HTMLInputElement | null;
    const checked = target ? target.checked : !this.selectedUrls().has(url);
    const next = new Set(this.selectedUrls());
    if (checked) {
      next.add(url);
    } else {
      next.delete(url);
    }
    this.selectedUrls.set(next);
  }

  toggleSelectAllVisible(): void {
    const list = this.filteredJobs();
    if (!list.length) return;
    const next = new Set(this.selectedUrls());
    const unselect = this.isAllVisibleSelected();
    for (const j of list) {
      if (!j?.url) continue;
      if (unselect) {
        next.delete(j.url);
      } else {
        next.add(j.url);
      }
    }
    this.selectedUrls.set(next);
  }

  clearSelection(): void {
    this.selectedUrls.set(new Set());
  }

  clearFilters(): void {
    this.dateRange.set('all');
    this.customStartDate.set('');
    this.customEndDate.set('');
    this.searchTerm.set('');
    this.onlyAuto.set(false);
    this.portalFilter.set('all');
    this.sortOrder.set('recent');
  }

  formatDateDisplay(d?: string): string {
    if (!d) return '-';
    const datePart = String(d).substring(0, 10);
    const parts = datePart.split('-');
    if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
    return d;
  }

  readonly getPortalName = getPortalDisplayName;

  encodePath(path: string): string {
    return encodeURIComponent(path || '');
  }

  runAi(job: Vaga, step: string): void {
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
        this.toast.error('Erro ao processar com IA: ' + (err.error?.detail || err.message));
      }
    });
  }

  private buildAppliedPayload(job: Vaga): {
    url: string;
    company?: string;
    role?: string;
    portal?: string;
    contact_channel?: string;
    contacted_email?: string;
  } {
    const isDirectRecruiter = typeof job?.url === 'string' && job.url.startsWith('recruiter://');
    const firstEmail = Array.isArray(job?.recruiter_emails) && job.recruiter_emails.length > 0
      ? job.recruiter_emails[0]
      : undefined;
    return {
      url: job.url,
      company: job.company,
      role: job.title || job.role,
      portal: job.portal,
      ...(isDirectRecruiter ? { contact_channel: 'recruiter_email', contacted_email: firstEmail } : {}),
    };
  }

  markApplied(job: Vaga): void {
    this.actionStatus.set(`Registrando candidatura para "${job.title || 'vaga'}"…`);
    this.api.markApplied(this.buildAppliedPayload(job)).subscribe({
      next: () => {
        this.actionStatus.set('');
        this.toast.success(`Candidatura para "${job.title || 'vaga'}" registrada.`);
        this.loadSaved(false);
      },
      error: (err) => {
        this.actionStatus.set('');
        this.toast.error('Erro ao registrar candidatura: ' + (err.error?.detail || err.message));
      }
    });
  }

  discardJob(job: Vaga): void {
    this.api.discardJob(job.url).subscribe({
      next: () => {
        this.toast.success('Vaga movida para Descartadas.');
        this.loadSaved(false);
      },
      error: (err) => this.toast.error('Erro ao descartar: ' + (err.error?.detail || err.message))
    });
  }

  reevaluateSelected(): void {
    const selected = this.visibleSelectedJobs();
    if (!selected.length || this.bulkBusy()) return;
    const urls = selected.map(j => j.url).filter(Boolean);
    if (!urls.length) return;

    this.bulkStatusMsg.set('');
    this.lastReevalCount = 0;
    this.reevalRunning.set(true);
    this.reevalCurrent.set(0);
    this.reevalTotal.set(urls.length);
    this.reevalPercent.set(0);
    this.reevalErrors.set(0);
    this.reevalCurrentTitle.set('Iniciando reavaliação com IA...');

    this.api.startBatchReevaluate(urls).subscribe({
      next: () => {
        this.pollReevalStatus();
      },
      error: (err) => {
        this.reevalRunning.set(false);
        this.bulkStatusMsg.set('');
        this.toast.error('Erro ao iniciar reavaliação em lote: ' + (err?.error?.detail || err?.message || 'Falha na comunicação'));
      }
    });
  }

  private checkInitialReevalStatus(): void {
    this.api.getSavedBatchStatus().subscribe({
      next: (st) => {
        if (st?.running) {
          this.applyReevalSnapshot(st);
          this.reevalRunning.set(true);
          this.pollReevalStatus();
        }
      },
      error: (err) => console.warn('Falha ao consultar reavaliação em andamento:', err)
    });
  }

  private applyReevalSnapshot(st: any): void {
    const cur = Number(st?.current || 0);
    const tot = Number(st?.total || 0);
    this.reevalCurrent.set(cur);
    this.reevalTotal.set(tot);
    this.reevalPercent.set(Math.min(100, Math.round(st?.percent || 0)));
    this.reevalErrors.set(Number(st?.errors || 0));
    if (st?.current_title) {
      this.reevalCurrentTitle.set(st.current_title);
    }
    if (st?.provider) {
      this.reevalProvider.set(st.provider);
    }
  }

  private pollReevalStatus(): void {
    this.cleanupReevalPolling();
    this.reevalPollInterval = setInterval(() => {
      if (this.reevalPollInFlight) return;
      this.reevalPollInFlight = true;
      this.api.getSavedBatchStatus().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
        next: (st) => {
          this.reevalPollInFlight = false;
          if (!st) return;
          this.applyReevalSnapshot(st);
          const cur = Number(st.current || 0);
          if (st.running) {
            if (cur > this.lastReevalCount) {
              this.lastReevalCount = cur;
              this.loadSaved(false);
            }
          } else {
            this.cleanupReevalPolling();
            this.reevalRunning.set(false);
            this.reevalPercent.set(100);
            const errs = Number(st.errors || 0);
            const total = Number(st.total || 0);
            const okCount = Math.max(0, total - errs);
            this.bulkStatusMsg.set(
              errs > 0
                ? `Reavaliação concluída: ${okCount} atualizada(s), ${errs} com erro.`
                : `Reavaliação com IA concluída para ${total} ${total === 1 ? 'vaga' : 'vagas'}.`
            );
            this.loadSaved(false);
            this.api.refreshCounts();
          }
        },
        error: (err) => {
          this.cleanupReevalPolling();
          this.reevalRunning.set(false);
          this.toast.error('Falha ao acompanhar reavaliação em lote: ' + (err?.error?.detail || err?.message || 'Erro de rede'));
        }
      });
    }, 1500);
  }

  markSelectedApplied(): void {
    const selected = this.visibleSelectedJobs();
    if (!selected.length || this.bulkBusy()) return;
    const n = selected.length;
    if (!confirm(`Enviar ${n} ${n === 1 ? 'vaga selecionada' : 'vagas selecionadas'} para a aba Candidaturas?`)) {
      return;
    }
    this.bulkActionLoading.set(true);
    this.bulkStatusMsg.set(`Enviando ${n} ${n === 1 ? 'vaga' : 'vagas'} para Candidaturas…`);
    this.api.markAppliedBatch(selected.map(j => this.buildAppliedPayload(j))).subscribe({
      next: (res) => {
        this.bulkActionLoading.set(false);
        const appliedCount = res?.applied ?? n;
        this.bulkStatusMsg.set(`${appliedCount} ${appliedCount === 1 ? 'vaga enviada' : 'vagas enviadas'} para Candidaturas.`);
        this.loadSaved(false);
      },
      error: (err) => {
        this.bulkActionLoading.set(false);
        this.bulkStatusMsg.set('');
        this.toast.error('Erro ao enviar vagas selecionadas: ' + (err?.error?.detail || err?.message));
      }
    });
  }

  discardSelected(): void {
    const selected = this.visibleSelectedJobs();
    if (!selected.length || this.bulkBusy()) return;
    const n = selected.length;
    if (!confirm(`Descartar ${n} ${n === 1 ? 'vaga selecionada' : 'vagas selecionadas'} e movê-${n === 1 ? 'la' : 'las'} para Descartadas?`)) {
      return;
    }
    this.bulkActionLoading.set(true);
    this.bulkStatusMsg.set(`Descartando ${n} ${n === 1 ? 'vaga' : 'vagas'}…`);
    this.api.discardJobsBatch(selected.map(j => j.url)).subscribe({
      next: (res) => {
        this.bulkActionLoading.set(false);
        const discCount = res?.discarded ?? n;
        this.bulkStatusMsg.set(`${discCount} ${discCount === 1 ? 'vaga movida' : 'vagas movidas'} para Descartadas.`);
        this.loadSaved(false);
      },
      error: (err) => {
        this.bulkActionLoading.set(false);
        this.bulkStatusMsg.set('');
        this.toast.error('Erro ao descartar vagas selecionadas: ' + (err?.error?.detail || err?.message));
      }
    });
  }

  undoAutoJob(job: Vaga): void {
    this.actionStatus.set(`Revertendo "${job.title || 'vaga'}"…`);
    this.autoMode.undoSingleJob({ url: job.url, job_id: job.id }).subscribe({
      next: () => {
        this.actionStatus.set('');
        this.toast.success('Promoção automática revertida.');
        this.loadSaved();
      },
      error: (err) => {
        this.actionStatus.set('');
        this.toast.error('Erro ao desfazer promoção automática: ' + (err.error?.detail || err.message));
      }
    });
  }

  copyRecruiterEmail(email: string): void {
    if (!email) return;
    navigator.clipboard.writeText(email).then(() => {
      this.copiedRecruiterEmail.set(email);
      if (this.copyTimer) {
        clearTimeout(this.copyTimer);
      }
      this.copyTimer = setTimeout(() => {
        this.copyTimer = null;
        if (this.copiedRecruiterEmail() === email) {
          this.copiedRecruiterEmail.set(null);
        }
      }, 2200);
    }).catch(() => this.toast.warning('Não foi possível copiar o e-mail para a área de transferência.'));
  }
}
