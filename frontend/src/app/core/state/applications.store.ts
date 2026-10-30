import { Injectable, inject, signal } from '@angular/core';
import { ApiService } from '../services/api.service';

@Injectable({
  providedIn: 'root'
})
export class ApplicationsStore {
  private readonly api = inject(ApiService);

  readonly applications = signal<any[]>([]);
  readonly isLoading = signal<boolean>(false);

  loadApplications(): void {
    this.isLoading.set(true);
    this.api.getApplications().subscribe({
      next: (apps) => {
        this.applications.set(apps);
        this.isLoading.set(false);
      },
      error: () => this.isLoading.set(false)
    });
  }
}

