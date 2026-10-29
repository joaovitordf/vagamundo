import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule, NavigationEnd } from '@angular/router';
import { filter } from 'rxjs/operators';
import { HeaderComponent } from './core/components/header/header.component';
import { SidebarComponent } from './core/components/sidebar/sidebar.component';
import { FooterComponent } from './core/components/footer/footer.component';

const ROUTE_META: Record<string, { title: string; icon: string }> = {
  '/buscar-vagas': { title: 'Buscar e Vagas', icon: 'bi-search' },
  '/me-interessam': { title: 'Vagas que Me Interessam', icon: 'bi-star' },
  '/candidaturas': { title: 'Minhas Candidaturas', icon: 'bi-send-check' },
  '/evolucao': { title: 'Evolução e Métricas', icon: 'bi-graph-up' },
  '/curriculos-cartas': { title: 'Currículos e Cartas Compilados', icon: 'bi-file-earmark-pdf' },
  '/descartadas': { title: 'Vagas Descartadas', icon: 'bi-trash3' },
  '/meu-perfil': { title: 'Meu Perfil', icon: 'bi-person-badge' },
  '/configuracoes': { title: 'Configurações do Assistente de IA', icon: 'bi-gear' }
};

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterModule, HeaderComponent, SidebarComponent, FooterComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css'
})
export class AppComponent {
  private readonly router = inject(Router);

  isCollapsed = false;
  mobileOpen = false;
  pageTitle = 'Buscar e Vagas';
  pageIcon = 'bi-search';

  constructor() {
    this.router.events.pipe(
      filter(event => event instanceof NavigationEnd)
    ).subscribe((event: any) => {
      const url = event.urlAfterRedirects || event.url;
      const meta = ROUTE_META[url] || { title: 'Vagamundo', icon: 'bi-compass' };
      this.pageTitle = meta.title;
      this.pageIcon = meta.icon;
      this.mobileOpen = false;
    });
  }

  toggleSidebar(): void {
    this.isCollapsed = !this.isCollapsed;
  }

  toggleMobile(): void {
    this.mobileOpen = !this.mobileOpen;
  }

  closeMobile(): void {
    this.mobileOpen = false;
  }
}
