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

  restoreJob(job: Vaga): void {
    this.api.restoreJob(job.url).subscribe({
      next: () => {
        this.toast.success(`Vaga "${job.title}" restaurada.`);
        this.loadDiscarded();
      },
      error: (err) => this.toast.error('Erro ao restaurar vaga: ' + (err?.error?.detail || err?.message || 'Falha na requisição'))
    });
  }

  clearDiscarded(): void {
    if (!this.allDiscarded().length) return;
    const ok = confirm(`Tem certeza que deseja limpar permanentemente ${this.allDiscarded().length} vagas descartadas da memória do sistema?`);
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
