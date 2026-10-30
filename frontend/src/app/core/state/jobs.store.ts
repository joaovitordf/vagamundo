import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from '../services/api.service';
import { Vaga } from '../models/vaga.model';

@Injectable({
  providedIn: 'root'
})
export class JobsStore {
  private readonly api = inject(ApiService);

  readonly jobs = signal<Vaga[]>([]);
  readonly savedJobs = signal<Vaga[]>([]);
  readonly discardedJobs = signal<Vaga[]>([]);
  readonly isLoading = signal<boolean>(false);
  readonly filterPortal = signal<string>('all');
  readonly filterWorkplace = signal<string>('all');
  readonly searchQuery = signal<string>('');

  readonly filteredJobs = computed(() => {
    let list = this.jobs();
    const portal = this.filterPortal();
    const workplace = this.filterWorkplace();
    const query = this.searchQuery().toLowerCase().trim();

    if (portal !== 'all') {
      list = list.filter(j => j.portal === portal);
    }
    if (workplace !== 'all') {
      list = list.filter(j => (j.workplace_type || '').toLowerCase().includes(workplace));
    }
    if (query) {
      list = list.filter(j =>
        (j.title || '').toLowerCase().includes(query) ||
        (j.company || '').toLowerCase().includes(query) ||
        (j.location || '').toLowerCase().includes(query)
      );
    }
    return list;
  });

  setJobs(jobs: Vaga[]): void {
    this.jobs.set(jobs);
  }

  markInterest(url: string, jobData?: Vaga): void {
    this.api.markDecision([url], 'interesse', jobData).subscribe(() => {
      this.jobs.update(list => list.filter(j => j.url !== url));
    });
  }

  discard(url: string): void {
    this.api.discardJob(url).subscribe(() => {
      this.jobs.update(list => list.filter(j => j.url !== url));
    });
  }
}

