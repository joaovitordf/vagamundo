import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';

export interface GeneratedDoc {
  name: string;
  kind: 'cv' | 'carta' | 'entrevista' | string;
  path: string;
  date: string;
  company?: string;
  role?: string;
  size_kb?: number;
}

@Component({
  selector: 'app-curriculos-cartas',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './curriculos-cartas.component.html',
  styleUrl: './curriculos-cartas.component.css'
})
export class CurriculosCartasComponent implements OnInit {
  private readonly api = inject(ApiService);

  kindFilter = '';
  loading = signal<boolean>(true);
  allDocs = signal<GeneratedDoc[]>([]);

  ngOnInit(): void {
    this.loadDocs();
  }

  loadDocs(): void {
    this.loading.set(true);
    this.api.getDocuments().subscribe({
      next: (docs) => {
        this.allDocs.set(docs || []);
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Erro ao carregar documentos:', err);
        this.loading.set(false);
      }
    });
  }

  filteredDocs(): GeneratedDoc[] {
    if (!this.kindFilter) return this.allDocs();
    return this.allDocs().filter(d => d.kind === this.kindFilter);
  }

  getDocTitle(doc: GeneratedDoc): string {
    if (doc.company && doc.role) {
      return `${doc.company} — ${doc.role}`;
    }
    if (doc.company) {
      return `${doc.company}`;
    }
    const raw = (doc.name || '')
      .replace(/\.pdf$/i, '')
      .replace(/^(cover_|main_|prep_)/i, '')
      .replace(/_/g, ' ')
      .trim();
    if (!raw) return 'Documento';
    return raw
      .split(' ')
      .map(w => w.length > 2 ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : w)
      .join(' ');
  }

  getKindLabel(kind: string): string {
    switch (kind) {
      case 'cv': return 'Currículo';
      case 'carta': return 'Carta';
      case 'entrevista': return 'Dossiê';
      default: return kind;
    }
  }

  encodePath(path: string): string {
    return encodeURIComponent(path || '');
  }

  deleteDoc(doc: GeneratedDoc): void {
    const isCv = doc.kind === 'cv';
    const msg = isCv
      ? `Atenção: Tem certeza que deseja excluir o currículo "${doc.name}"?`
      : `Deseja excluir o documento "${doc.name}"?`;
    if (!confirm(msg)) return;

    this.api.deleteDocument(doc.path).subscribe({
      next: () => {
        this.loadDocs();
      },
      error: (err) => alert('Erro ao excluir documento: ' + (err.error?.detail || err.message))
    });
  }

  clearGeneratedDocs(): void {
    const ok = confirm('Tem certeza que deseja limpar cartas e dossiês de entrevista antigos?\n\nSeus currículos (CVs) serão mantidos 100% protegidos e salvos.');
    if (!ok) return;

    this.loading.set(true);
    this.api.clearDocuments(true).subscribe({
      next: () => {
        this.loadDocs();
      },
      error: (err) => {
        this.loading.set(false);
        alert('Erro ao limpar arquivos: ' + (err.error?.detail || err.message));
      }
    });
  }
}
