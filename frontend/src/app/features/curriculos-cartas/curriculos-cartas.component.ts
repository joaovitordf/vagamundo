import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

interface GeneratedDoc {
  name: string;
  kind: 'cv' | 'carta' | 'entrevista';
  path: string;
  date: string;
}

@Component({
  selector: 'app-curriculos-cartas',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './curriculos-cartas.component.html',
  styleUrl: './curriculos-cartas.component.css'
})
export class CurriculosCartasComponent implements OnInit {
  kindFilter = '';

  allDocs = signal<GeneratedDoc[]>([
    {
      name: 'Currículo - Full-Stack Developer (ATS / Tech)',
      kind: 'cv',
      path: 'cv/Curriculum.pdf',
      date: '2026-10-25'
    },
    {
      name: 'Carta de Apresentação - ATA Services Plus',
      kind: 'carta',
      path: 'cover_letters/cover_ata_services_plus.pdf',
      date: '2026-10-25'
    },
    {
      name: 'Dossiê STAR de Entrevista - Senior Role',
      kind: 'entrevista',
      path: 'documents/interview/dossie_senior_engineer.pdf',
      date: '2026-10-24'
    }
  ]);

  ngOnInit(): void {}

  filteredDocs(): GeneratedDoc[] {
    if (!this.kindFilter) return this.allDocs();
    return this.allDocs().filter(d => d.kind === this.kindFilter);
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
    return encodeURIComponent(path);
  }
}
