import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Vaga } from '../../../core/models/vaga.model';

@Component({
  selector: 'app-job-card',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="card h-100 shadow-sm border-0 job-card">
      <div class="card-body d-flex flex-column">
        <div class="d-flex justify-content-between align-items-start mb-2">
          <span class="badge bg-light text-dark border">{{ job.portal || 'portal' }}</span>
          <span *ngIf="job.date" class="text-muted small">{{ job.date }}</span>
        </div>
        <h5 class="card-title text-primary mb-1">
          <a [href]="job.url" target="_blank" rel="noopener noreferrer" class="text-decoration-none">
            {{ job.title }}
          </a>
        </h5>
        <h6 class="card-subtitle text-muted mb-2">{{ job.company }}</h6>
        <p *ngIf="job.location" class="card-text small text-secondary mb-2">
          📍 {{ job.location }}
        </p>
        <p *ngIf="job.description" class="card-text small text-body-secondary flex-grow-1 job-description">
          {{ job.description }}
        </p>
        <div class="mt-3 pt-2 border-top d-flex gap-2 justify-content-end">
          <button type="button" class="btn btn-sm btn-outline-danger" (click)="onDiscard()">
            Descartar
          </button>
          <button type="button" class="btn btn-sm btn-primary" (click)="onInterest()">
            Me interessa
          </button>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .job-card { transition: transform 0.15s ease-in-out, box-shadow 0.15s ease-in-out; }
    .job-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.08) !important; }
    .job-description {
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
  `]
})
export class JobCardComponent {
  @Input({ required: true }) job!: Vaga;
  @Output() interest = new EventEmitter<Vaga>();
  @Output() discard = new EventEmitter<Vaga>();

  onInterest(): void {
    this.interest.emit(this.job);
  }

  onDiscard(): void {
    this.discard.emit(this.job);
  }
}

