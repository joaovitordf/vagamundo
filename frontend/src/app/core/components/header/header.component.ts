import { Component, DestroyRef, Input, Output, EventEmitter, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs/operators';
import { ThemeService } from '../../services/theme.service';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './header.component.html',
  styleUrl: './header.component.css'
})
export class HeaderComponent implements OnInit {
  readonly theme = inject(ThemeService);
  private readonly api = inject(ApiService);
  private readonly router = inject(Router, { optional: true });
  private readonly destroyRef = inject(DestroyRef);

  @Input() pageTitle = 'Buscar e Vagas';
  @Input() pageIcon = 'bi-search';
  @Output() toggleMobile = new EventEmitter<void>();

  engineLabel = 'IA Ativa';
  engineAvailable = true;

  ngOnInit(): void {
    this.refreshEngineStatus();
    this.router?.events.pipe(
      filter(event => event instanceof NavigationEnd),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(() => {
      this.refreshEngineStatus();
    });
  }

  refreshEngineStatus(): void {
    this.api.getSearchStatus().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (st) => {
        const prov = st?.provider;
        if (prov) {
          this.engineAvailable = prov.available !== false;
          if (prov.available === false) {
            this.engineLabel = prov.label || 'IA Inativa';
          } else if (prov.label) {
            this.engineLabel = prov.label;
          }
        }
      },
      error: (err) => console.warn('Falha ao consultar status do provedor de IA:', err)
    });
  }
}
