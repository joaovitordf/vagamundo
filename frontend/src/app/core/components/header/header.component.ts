import { Component, Input, Output, EventEmitter, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
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

  @Input() pageTitle = 'Buscar e Vagas';
  @Input() pageIcon = 'bi-search';
  @Output() toggleMobile = new EventEmitter<void>();

  engineLabel = 'IA Ativa';

  ngOnInit(): void {
    this.api.getSearchStatus().subscribe({
      next: (st) => {
        if (st && st.provider && st.provider.label) {
          this.engineLabel = st.provider.label;
        }
      },
      error: () => {}
    });
  }
}
