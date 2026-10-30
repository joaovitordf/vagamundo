import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-filter-bar',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="row g-2 mb-3 align-items-center bg-body-tertiary p-3 rounded-3 border">
      <div class="col-md-5">
        <div class="input-group">
          <span class="input-group-text bg-white border-end-0">🔍</span>
          <input
            type="text"
            class="form-control border-start-0"
            placeholder="Filtrar por título, empresa ou cidade..."
            [(ngModel)]="searchQuery"
            (ngModelChange)="searchChange.emit(searchQuery)"
          />
        </div>
      </div>
      <div class="col-md-3">
        <select
          class="form-select"
          [(ngModel)]="selectedPortal"
          (ngModelChange)="portalChange.emit(selectedPortal)"
        >
          <option value="all">Todos os portais</option>
          <option *ngFor="let p of portals" [value]="p">{{ p }}</option>
        </select>
      </div>
      <div class="col-md-4 text-end">
        <span class="text-muted small">
          Exibindo <strong>{{ filteredCount }}</strong> de <strong>{{ totalCount }}</strong> vagas
        </span>
      </div>
    </div>
  `
})
export class FilterBarComponent {
  @Input() portals: string[] = [];
  @Input() filteredCount = 0;
  @Input() totalCount = 0;

  @Input() searchQuery = '';
  @Output() searchChange = new EventEmitter<string>();

  @Input() selectedPortal = 'all';
  @Output() portalChange = new EventEmitter<string>();
}

