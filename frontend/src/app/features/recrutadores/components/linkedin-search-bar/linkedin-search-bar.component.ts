import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../../../core/services/api.service';
import { ToastService } from '../../../../core/services/toast.service';
import { RecruiterPost } from '../../../../core/models/vaga.model';
import {
  BilingualTermEntry,
  SearchLanguageMode,
  normalizeBilingualKey,
} from '../../../../shared/utils/bilingual-terms.util';
import {
  analyzeLinkedInQueryHealth,
  buildFormattedLinkedInSearch,
  buildGoogleXRayLinkedInPostsUrl,
  buildLinkedInContentSearchUrl,
  LINKEDIN_QUERY_PRESETS,
  LinkedInDateOption,
  LinkedInQueryPreset,
} from '../../../../shared/utils/linkedin-search-formatter.util';

export const BILINGUAL_TERM_CACHE_KEY = 'vagamundo.bilingualTermCache.v1';
const MAX_CACHED_TERMS = 200;

export interface LinkedInPasteImportedEvent {
  posts: RecruiterPost[];
  matchedIds: number[];
  message: string;
}

export interface PastedReviewItem {
  post: RecruiterPost;
  evaluating: boolean;
  evalError: string | null;
  busy: boolean;
  decision: 'pending' | 'interested';
}

function loadCachedAiTerms(): Record<string, BilingualTermEntry> {
  try {
    const raw = localStorage.getItem(BILINGUAL_TERM_CACHE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const clean: Record<string, BilingualTermEntry> = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (!v || typeof v !== 'object') continue;
      const entry = v as BilingualTermEntry;
      clean[k] = {
        en: typeof entry.en === 'string' && entry.en.trim() ? entry.en.trim() : null,
        pt: typeof entry.pt === 'string' && entry.pt.trim() ? entry.pt.trim() : null,
      };
    }
    return clean;
  } catch {
    return {};
  }
}

function persistCachedAiTerms(cache: Record<string, BilingualTermEntry>): void {
  try {
    const entries = Object.entries(cache);
    const trimmed = entries.length > MAX_CACHED_TERMS ? entries.slice(entries.length - MAX_CACHED_TERMS) : entries;
    localStorage.setItem(BILINGUAL_TERM_CACHE_KEY, JSON.stringify(Object.fromEntries(trimmed)));
  } catch {
    // Ignore storage quota/unavailable errors
  }
}

@Component({
  selector: 'app-linkedin-search-bar',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './linkedin-search-bar.component.html',
  styleUrl: './linkedin-search-bar.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LinkedinSearchBarComponent {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastService);
  private readonly destroyRef = inject(DestroyRef);

  private readonly filterTextSig = signal<string>('');
  private readonly jobAgeFilterSig = signal<string>('');

  private readonly aiTermOverrides = signal<Record<string, BilingualTermEntry>>(loadCachedAiTerms());
  private readonly inFlightAiKeys = new Set<string>();
  private readonly attemptedSessionKeys = new Set<string>();

  @Input() set filterText(value: string) {
    const next = value || '';
    if (next !== this.filterTextSig()) {
      this.linkedInCustomQuery.set(null);
    }
    this.filterTextSig.set(next);
  }

  @Input() set jobAgeFilter(value: string) {
    const next = value || '';
    if (next !== this.jobAgeFilterSig()) {
      this.linkedInCustomQuery.set(null);
    }
    this.jobAgeFilterSig.set(next);
  }

  @Input() linkedInPostsCount = 0;

  @Output() postsImported = new EventEmitter<LinkedInPasteImportedEvent>();
  @Output() postsEvaluated = new EventEmitter<RecruiterPost[]>();
  @Output() postInterested = new EventEmitter<RecruiterPost>();
  @Output() postDismissed = new EventEmitter<number>();
  @Output() pasteError = new EventEmitter<string>();

  readonly linkedInPresets = LINKEDIN_QUERY_PRESETS;
  readonly linkedInPreset = signal<LinkedInQueryPreset>('jobs_lean');
  readonly linkedInLanguageMode = signal<SearchLanguageMode>('both');
  readonly linkedInDateOverride = signal<LinkedInDateOption>('auto');
  readonly linkedInCustomQuery = signal<string | null>(null);
  readonly expandingWithAi = signal<boolean>(false);

  readonly showPastePanel = signal<boolean>(false);
  readonly pasteText = signal<string>('');
  readonly pasteUrl = signal<string>('');
  readonly submittingPaste = signal<boolean>(false);
  readonly pastedReviews = signal<PastedReviewItem[]>([]);

  readonly generatedLinkedInSearch = computed(() =>
    buildFormattedLinkedInSearch({
      filterText: this.filterTextSig(),
      preset: this.linkedInPreset(),
      languageMode: this.linkedInLanguageMode(),
      jobAgeFilter: this.jobAgeFilterSig(),
      includeFilters: false,
      dateOverride: this.linkedInDateOverride(),
      aiTermOverrides: this.aiTermOverrides(),
    })
  );

  readonly activeLinkedInQuery = computed(() => {
    const custom = this.linkedInCustomQuery();
    return custom !== null ? custom : this.generatedLinkedInSearch().query;
  });

  readonly activeQueryHealth = computed(() =>
    analyzeLinkedInQueryHealth(this.activeLinkedInQuery())
  );

  readonly activeLinkedInUrl = computed(() =>
    buildLinkedInContentSearchUrl(this.activeLinkedInQuery(), this.generatedLinkedInSearch().datePosted)
  );

  readonly activeGoogleXRayUrl = computed(() =>
    buildGoogleXRayLinkedInPostsUrl(
      this.activeLinkedInQuery(),
      this.generatedLinkedInSearch().datePosted,
      this.linkedInPreset()
    )
  );

  readonly addedVariantBadge = computed(() => {
    const variants = this.generatedLinkedInSearch().addedVariants;
    if (!variants.length) return '';
    return `+ ${variants.slice(0, 2).join(', ')}`;
  });

  constructor() {
    effect((onCleanup) => {
      const pending = this.generatedLinkedInSearch().pendingAiTerms;
      if (!pending.length) return;
      if (this.linkedInCustomQuery() !== null) return;
      if (typeof this.api?.expandRecruiterSearchTerm !== 'function') return;

      const targetTerm = pending[0];
      const key = normalizeBilingualKey(targetTerm);
      if (!key || this.inFlightAiKeys.has(key) || this.attemptedSessionKeys.has(key)) {
        return;
      }

      const timer = setTimeout(() => {
        if (this.inFlightAiKeys.has(key) || this.attemptedSessionKeys.has(key)) return;
        this.inFlightAiKeys.add(key);
        this.attemptedSessionKeys.add(key);
        this.expandingWithAi.set(true);

        const sub = this.api.expandRecruiterSearchTerm(targetTerm).subscribe({
          next: (res) => {
            this.inFlightAiKeys.delete(key);
            this.expandingWithAi.set(this.inFlightAiKeys.size > 0);
            if (!res) return;
            const entry: BilingualTermEntry = {
              en: res.en || null,
              pt: res.pt || null,
            };
            if (entry.en || entry.pt || res.source === 'ai' || res.source === 'cache') {
              this.aiTermOverrides.update(prev => {
                const next = { ...prev, [key]: entry };
                persistCachedAiTerms(next);
                return next;
              });
            }
          },
          error: () => {
            this.inFlightAiKeys.delete(key);
            this.expandingWithAi.set(this.inFlightAiKeys.size > 0);
          },
        });

        this.destroyRef.onDestroy(() => sub.unsubscribe());
      }, 450);

      onCleanup(() => clearTimeout(timer));
    }, { allowSignalWrites: true });
  }

  setLinkedInPreset(preset: LinkedInQueryPreset): void {
    this.linkedInPreset.set(preset);
    this.linkedInCustomQuery.set(null);
  }

  setLinkedInLanguageMode(mode: SearchLanguageMode): void {
    this.linkedInLanguageMode.set(mode);
    this.linkedInCustomQuery.set(null);
  }

  setLinkedInDateOverride(option: LinkedInDateOption): void {
    this.linkedInDateOverride.set(option);
    this.linkedInCustomQuery.set(null);
  }

  onLinkedInQueryInput(query: string): void {
    this.linkedInCustomQuery.set(String(query ?? ''));
  }

  resetLinkedInQuery(): void {
    this.linkedInCustomQuery.set(null);
  }

  copyLinkedInQuery(): void {
    const query = this.activeLinkedInQuery().trim();
    if (!query) return;
    this.copyTextWithFeedback(query, 'Pesquisa booleana do LinkedIn copiada!');
  }

  copyEmail(email: string): void {
    const clean = String(email || '').trim();
    if (!clean) return;
    this.copyTextWithFeedback(clean, `E-mail ${clean} copiado!`);
  }

  togglePastePanel(): void {
    this.showPastePanel.update(v => !v);
  }

  isExternalPostUrl(url?: string | null): boolean {
    return /^https?:\/\//i.test(String(url || '').trim());
  }

  submitManualPaste(): void {
    const rawText = this.pasteText().trim();
    if (!rawText) {
      this.toast.warning('Cole o texto da publicação do LinkedIn antes de avaliar.');
      return;
    }
    if (this.submittingPaste()) return;

    this.submittingPaste.set(true);
    const isBatch =
      rawText.startsWith('VAGAMUNDO_LI_BATCH_V1:')
      || rawText.startsWith('{')
      || rawText.startsWith('[')
      || /\r?\n\s*-{3,}\s*\r?\n/.test(rawText);

    if (isBatch) {
      this.api.pasteRecruiterPostsBatch({ raw_batch_text: rawText, allow_without_email: true }).subscribe({
        next: (res) => {
          const importedPosts = res?.posts || [];
          const importedIds = importedPosts.map(p => p.id).filter(Boolean);
          const count = Number(res?.imported || 0) + Number(res?.updated || 0);
          const msg = count > 0
            ? `${count} publicação(ões) importada(s) do LinkedIn!`
            : 'Publicação(ões) já estavam registradas no Radar.';
          this.handlePasteSuccess(importedPosts, importedIds, msg);
        },
        error: (err) => this.handlePasteError(err, 'Não foi possível importar as publicações coladas.'),
      });
      return;
    }

    const url = this.pasteUrl().trim() || undefined;
    this.api.pasteRecruiterPost({ raw_text: rawText, url, allow_without_email: true }).subscribe({
      next: (res) => {
        const post = res?.post;
        this.handlePasteSuccess(
          post ? [post] : [],
          post?.id ? [post.id] : [],
          'Publicação importada do LinkedIn com sucesso!'
        );
      },
      error: (err) => this.handlePasteError(err, 'Não foi possível importar a publicação colada.'),
    });
  }

  retryEvaluateReview(postId: number): void {
    this.evaluatePastedPosts([postId]);
  }

  saveReviewAsInterested(item: PastedReviewItem): void {
    if (item.busy || item.decision === 'interested') return;
    if (typeof this.api?.markRecruiterPostInterested !== 'function') return;

    this.updateReviewItem(item.post.id, prev => ({ ...prev, busy: true }));
    this.api.markRecruiterPostInterested(item.post.id).subscribe({
      next: () => {
        const updatedPost: RecruiterPost = { ...item.post, job_status: 'interested' };
        this.updateReviewItem(item.post.id, prev => ({
          ...prev,
          post: updatedPost,
          busy: false,
          decision: 'interested',
        }));
        this.toast.success(`"${updatedPost.title}" salva em Me Interessam!`);
        this.postInterested.emit(updatedPost);
      },
      error: (err) => {
        const detail = err?.error?.detail || err?.message || 'Não foi possível salvar em Me Interessam.';
        this.updateReviewItem(item.post.id, prev => ({ ...prev, busy: false }));
        this.toast.error(detail);
        this.pasteError.emit(detail);
      },
    });
  }

  discardReview(item: PastedReviewItem): void {
    if (item.busy) return;
    if (typeof this.api?.dismissRecruiterPost !== 'function') return;

    this.updateReviewItem(item.post.id, prev => ({ ...prev, busy: true }));
    this.api.dismissRecruiterPost(item.post.id).subscribe({
      next: () => {
        this.pastedReviews.update(list => list.filter(r => r.post.id !== item.post.id));
        this.toast.success('Vaga movida para Descartadas.');
        this.postDismissed.emit(item.post.id);
      },
      error: (err) => {
        const detail = err?.error?.detail || err?.message || 'Não foi possível descartar esta publicação.';
        this.updateReviewItem(item.post.id, prev => ({ ...prev, busy: false }));
        this.toast.error(detail);
        this.pasteError.emit(detail);
      },
    });
  }

  closeReviewCard(postId: number): void {
    this.pastedReviews.update(list => list.filter(r => r.post.id !== postId));
  }

  getClassificationLabel(cls?: string | null): string {
    if (cls === 'banco_talentos') return 'Banco de talentos';
    if (cls === 'nao_e_vaga') return 'Não é vaga';
    return 'Vaga ativa';
  }

  private handlePasteSuccess(importedPosts: RecruiterPost[], matchedIds: number[], message: string): void {
    this.submittingPaste.set(false);
    this.pasteText.set('');
    this.pasteUrl.set('');
    this.toast.success(message);

    const canAutoTriage = typeof this.api?.triageRecruiterPosts === 'function';
    const pendingEvalIds: number[] = [];

    if (importedPosts.length > 0) {
      const newItems: PastedReviewItem[] = importedPosts.map(post => {
        const needsEval = canAutoTriage && !post.ai_evaluated_at;
        if (needsEval && post.id) {
          pendingEvalIds.push(post.id);
        }
        return {
          post,
          evaluating: needsEval,
          evalError: null,
          busy: false,
          decision: post.job_status === 'interested' || post.auto_promoted ? 'interested' : 'pending',
        };
      });

      const incomingIds = new Set(newItems.map(i => i.post.id));
      this.pastedReviews.update(prev => [
        ...newItems,
        ...prev.filter(item => !incomingIds.has(item.post.id)),
      ]);
    }

    this.postsImported.emit({ posts: importedPosts, matchedIds, message });

    if (pendingEvalIds.length > 0) {
      this.evaluatePastedPosts(pendingEvalIds);
    }
  }

  private evaluatePastedPosts(postIds: number[]): void {
    const cleanIds = postIds.filter(Boolean);
    if (!cleanIds.length || typeof this.api?.triageRecruiterPosts !== 'function') return;

    const idSet = new Set(cleanIds);
    this.pastedReviews.update(list =>
      list.map(item =>
        idSet.has(item.post.id)
          ? { ...item, evaluating: true, evalError: null }
          : item
      )
    );

    this.api.triageRecruiterPosts({ post_ids: cleanIds, limit: Math.max(cleanIds.length, 5) }).subscribe({
      next: (res) => {
        const updatedMap = new Map<number, RecruiterPost>();
        for (const p of res?.posts || []) {
          if (p?.id) updatedMap.set(p.id, p);
        }

        this.pastedReviews.update(list =>
          list.map(item => {
            if (!idSet.has(item.post.id)) return item;
            const refreshed = updatedMap.get(item.post.id);
            if (refreshed) {
              return {
                ...item,
                post: refreshed,
                evaluating: false,
                evalError: null,
                decision: refreshed.job_status === 'interested' || refreshed.auto_promoted
                  ? 'interested'
                  : item.decision,
              };
            }
            return {
              ...item,
              evaluating: false,
              evalError: item.post.ai_evaluated_at
                ? null
                : 'A IA não retornou uma nota para esta publicação. Você pode tentar novamente ou decidir abaixo.',
            };
          })
        );

        if (updatedMap.size > 0) {
          this.postsEvaluated.emit(Array.from(updatedMap.values()));
        }
      },
      error: (err) => {
        const detail = err?.error?.detail || err?.message || 'Não foi possível avaliar com IA agora.';
        this.pastedReviews.update(list =>
          list.map(item =>
            idSet.has(item.post.id)
              ? { ...item, evaluating: false, evalError: detail }
              : item
          )
        );
      },
    });
  }

  private updateReviewItem(postId: number, updater: (item: PastedReviewItem) => PastedReviewItem): void {
    this.pastedReviews.update(list =>
      list.map(item => (item.post.id === postId ? updater(item) : item))
    );
  }

  private handlePasteError(err: any, fallbackMsg: string): void {
    this.submittingPaste.set(false);
    const detail = err?.error?.detail || err?.message || fallbackMsg;
    this.toast.error(detail);
    this.pasteError.emit(detail);
  }

  private copyTextWithFeedback(text: string, successToast: string): void {
    const done = () => this.toast.success(successToast);
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => {
        this.toast.error('Não foi possível copiar para a área de transferência.');
      });
    } else {
      done();
    }
  }
}
