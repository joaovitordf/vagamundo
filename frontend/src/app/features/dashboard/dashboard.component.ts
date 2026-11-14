import { Component, DestroyRef, OnInit, inject, signal, computed } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { ApiService } from '../../core/services/api.service';
import { DashboardStats, DashboardMonthlyPoint, DashboardDailyPoint, DashboardStatusPoint, DashboardPortalPoint, DashboardActivityPoint } from '../../core/models/vaga.model';
import { PortalBadgeComponent } from '../../shared/components/portal-badge.component';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterModule, PortalBadgeComponent],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.css'
})
export class DashboardComponent implements OnInit {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);

  stats = signal<DashboardStats | null>(null);
  loading = signal<boolean>(true);
  errorMsg = signal<string>('');
  selectedPeriod = signal<'1m' | '6m' | '12m'>('1m'); // '1m' inicial conforme escolha do usuário!
  sortDirection = signal<'desc' | 'asc'>('desc'); // 'desc' por padrão: dias mais recentes primeiro!

  displayDailyTimeline = computed(() => {
    const list = this.stats()?.daily_timeline || [];
    if (this.sortDirection() === 'asc') {
      return [...list].sort((a, b) => a.date.localeCompare(b.date));
    }
    return [...list].sort((a, b) => b.date.localeCompare(a.date));
  });

  displayMonthlyTimeline = computed(() => {
    const list = this.stats()?.monthly_timeline || [];
    if (this.sortDirection() === 'asc') {
      return [...list].sort((a, b) => a.month_key.localeCompare(b.month_key));
    }
    return [...list].sort((a, b) => b.month_key.localeCompare(a.month_key));
  });

  ngOnInit(): void {
    this.loadStats(1);
  }

  toggleSortDirection(): void {
    this.sortDirection.set(this.sortDirection() === 'desc' ? 'asc' : 'desc');
  }

  setPeriod(period: '1m' | '6m' | '12m'): void {
    this.selectedPeriod.set(period);
    const months = period === '1m' ? 1 : (period === '6m' ? 6 : 12);
    this.loadStats(months);
  }

  loadStats(months?: number): void {
    this.loading.set(true);
    this.errorMsg.set('');

    const period = this.selectedPeriod();
    const queryMonths = months ?? (period === '1m' ? 1 : (period === '12m' ? 12 : 6));
    this.api.getDashboardStats(queryMonths).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (data) => {
        this.stats.set(data);
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Erro ao carregar dados do dashboard:', err);
        this.errorMsg.set('Não foi possível carregar as estatísticas do dashboard.');
        this.loading.set(false);
      }
    });
  }

  // Cálculos para barras relativas
  getMaxMonthlyCount(): number {
    const timeline = this.stats()?.monthly_timeline || [];
    if (timeline.length === 0) return 1;
    const max = Math.max(...timeline.map(m => m.count));
    return max > 0 ? max : 1;
  }

  getMonthlyPercent(count: number): number {
    const max = this.getMaxMonthlyCount();
    return Math.round((count / max) * 100);
  }

  getMaxDailyCount(): number {
    const daily = this.stats()?.daily_timeline || [];
    if (daily.length === 0) return 1;
    const max = Math.max(...daily.map(d => d.count));
    return max > 0 ? max : 1;
  }

  getDailyPercent(count: number): number {
    const max = this.getMaxDailyCount();
    return Math.round((count / max) * 100);
  }

  formatDate(d?: string): string {
    if (!d) return '-';
    const datePart = String(d).substring(0, 10);
    const parts = datePart.split('-');
    if (parts.length === 3) return `${parts[2]}/${parts[1]}/${parts[0]}`;
    return d;
  }
}
