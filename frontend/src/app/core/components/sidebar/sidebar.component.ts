import { Component, Input, Output, EventEmitter, OnInit, inject, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { ApiService } from '../../services/api.service';

export interface NavItem {
  label: string;
  route: string;
  icon: string;
  count?: number;
  badgeClass?: string;
}

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.css'
})
export class SidebarComponent implements OnInit {
  @Input() isCollapsed = false;
  @Output() toggleCollapse = new EventEmitter<void>();

  private readonly api = inject(ApiService);

  navItems: NavItem[] = [
    { label: 'Dashboard', route: '/dashboard', icon: 'bi-speedometer2' },
    { label: 'Meu Perfil', route: '/meu-perfil', icon: 'bi-person-badge' },
    { label: 'Buscar e Vagas', route: '/buscar-vagas', icon: 'bi-search' },
    { label: 'Me Interessam', route: '/me-interessam', icon: 'bi-star' },
    { label: 'Candidaturas', route: '/candidaturas', icon: 'bi-send-check' },
    { label: 'Evolução', route: '/evolucao', icon: 'bi-graph-up' },
    { label: 'Currículos e Cartas', route: '/curriculos-cartas', icon: 'bi-file-earmark-pdf' },
    { label: 'Descartadas', route: '/descartadas', icon: 'bi-trash3' },
    { label: 'Configurações', route: '/configuracoes', icon: 'bi-gear' }
  ];

  constructor() {
    effect(() => {
      const vagas = this.api.sessionVagas();
      this.updateCount('/buscar-vagas', this.api.hasSearchedInSession() ? vagas.length : 0);
    });
    effect(() => {
      this.updateCount('/me-interessam', this.api.savedCount());
    });
    effect(() => {
      this.updateCount('/candidaturas', this.api.applicationsCount());
    });
    effect(() => {
      this.updateCount('/descartadas', this.api.discardedCount());
    });
  }

  ngOnInit(): void {
    this.api.refreshCounts();
  }

  private updateCount(route: string, count: number): void {
    const item = this.navItems.find(i => i.route === route);
    if (item) {
      item.count = count;
    }
  }
}
