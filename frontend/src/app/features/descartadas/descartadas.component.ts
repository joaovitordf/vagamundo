import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';
import { ToastService } from '../../core/services/toast.service';
import { Vaga } from '../../core/models/vaga.model';
import {
  getPortalDisplayName,
  getWorkModelLabel,
  matchesTextFilter,
  resolveEffectiveWorkModel,
  resolveGeo,
} from '../../core/utils/job-filters.util';
import { JobBadgesComponent } from '../../shared/components/job-badges.component';
import { PortalBadgeComponent } from '../../shared/components/portal-badge.component';

@Component({
  selector: 'app-descartadas',
  standalone: true,
  imports: [CommonModule, FormsModule, JobBadgesComponent, PortalBadgeComponent],
  templateUrl: './descartadas.component.html',
  styleUrl: './descartadas.component.css'
})
export class DescartadasComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastService);

  allDiscarded = signal<Vaga[]>([]);
  filteredJobs = signal<Vaga[]>([]);
  filterText = '';
  loading = signal<boolean>(true);
  deletingUrls = signal<Set<string>>(new Set());

  ngOnInit(): void {
    this.loadDiscarded();
  }

  loadDiscarded(): void {
    this.loading.set(true);
    this.api.getDiscarded().subscribe({
      next: (jobs) => {
        this.allDiscarded.set(jobs || []);
        this.onFilterChange();
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Erro ao carregar descartadas:', err);
        this.loading.set(false);
        this.toast.error('Não foi possível carregar as vagas descartadas.');
      }
    });
  }

  onFilterChange(): void {
    const q = this.filterText.trim();
    if (!q) {
      this.filteredJobs.set(this.allDiscarded());
      return;
    }
    this.filteredJobs.set(
      this.allDiscarded().filter(j => {
        const geo = resolveGeo(j);
        const effModel = resolveEffectiveWorkModel(j);
        const hay = `${j.title || ''} ${j.company || ''} ${j.location || ''} ${geo.label || ''} ${j.portal || ''} ${getPortalDisplayName(j.portal)} ${j.workplace_type || ''} ${getWorkModelLabel(effModel)}`;
        return matchesTextFilter(hay, q);
      })
    );
  }

  readonly getPortalName = getPortalDisplayName;

  isDeleting(url?: string | null): boolean {
    if (!url) return false;
    return this.deletingUrls().has(url);
  }

  isExternalHttpUrl(url?: string | null): boolean {
    return !!url && /^https?:\/\//i.test(url.trim());
  }

  restoreJob(job: Vaga): void {
    this.api.restoreJob(job.url).subscribe({
      next: () => {
        this.toast.success(`Vaga "${job.title}" restaurada.`);
        this.loadDiscarded();
      },
      error: (err) => this.toast.error('Erro ao restaurar vaga: ' + (err?.error?.detail || err?.message || 'Falha na requisição'))
    });
  }

  deleteFromDb(job: Vaga): void {
    const targetUrl = (job.url || '').trim();
    if (!targetUrl || this.isDeleting(targetUrl)) return;
    const label = job.title || targetUrl;
    const ok = confirm(
      `Excluir definitivamente "${label}" do banco de dados? Esta ação apaga a vaga, avaliações e o vínculo no histórico de recrutadores e não pode ser desfeita.`
    );
    if (!ok) return;

    this.deletingUrls.update(set => {
      const next = new Set(set);
      next.add(targetUrl);
      return next;
    });

    this.api.deleteDiscardedFromDb([targetUrl]).subscribe({
      next: () => {
        this.deletingUrls.update(set => {
          const next = new Set(set);
          next.delete(targetUrl);
          return next;
        });
        this.toast.success(`Vaga "${job.title || 'selecionada'}" excluída do BD.`);
        this.loadDiscarded();
      },
      error: (err) => {
        this.deletingUrls.update(set => {
          const next = new Set(set);
          next.delete(targetUrl);
          return next;
        });
        this.toast.error('Erro ao excluir vaga do BD: ' + (err?.error?.detail || err?.message || 'Falha na requisição'));
      }
    });
  }

  clearDiscarded(): void {
    if (!this.allDiscarded().length) return;
    const ok = confirm(`Tem certeza que deseja excluir definitivamente todas as ${this.allDiscarded().length} vagas descartadas do banco de dados?`);
    if (!ok) return;

    this.loading.set(true);
    this.api.clearDiscarded().subscribe({
      next: () => {
        this.toast.success('Lista de vagas descartadas limpa.');
        this.loadDiscarded();
      },
      error: (err) => {
        this.loading.set(false);
        this.toast.error('Erro ao limpar vagas descartadas: ' + (err?.error?.detail || err?.message || 'Falha na requisição'));
      }
    });
  }
}
