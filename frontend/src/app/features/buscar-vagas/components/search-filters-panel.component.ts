import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  HostListener,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { SearchStateService } from '../../../core/services/search-state.service';
import {
  AVAILABLE_PORTALS,
  PORTAL_CATEGORIES,
  PortalOption,
} from '../../../core/utils/job-filters.util';

@Component({
  selector: 'app-search-filters-panel',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './search-filters-panel.component.html',
  styleUrl: './search-filters-panel.component.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SearchFiltersPanelComponent {
  readonly state = inject(SearchStateService);

  @Input() searching = false;
  @Input() autoRunning = false;
  @Input() autoCancelling = false;
  @Input() hasTriagedJobs = false;
  @Input() triagedCount = 0;
  @Input() searchStatus = '';
  @Input() showProgressPanel = false;

  @Output() filterChange = new EventEmitter<void>();
  @Output() pickRandomCv = new EventEmitter<void>();
  @Output() clearTextFilter = new EventEmitter<void>();
  @Output() searchTrigger = new EventEmitter<void>();
  @Output() autoTrigger = new EventEmitter<void>();
  @Output() autoCancel = new EventEmitter<void>();
  @Output() autoConfigChange = new EventEmitter<void>();

  readonly availablePortals = AVAILABLE_PORTALS;
  readonly portalCategories = PORTAL_CATEGORIES;
  readonly portalsDropdownOpen = signal<boolean>(false);
  readonly selectedPortalIds = this.state.selectedPortalIds;
  readonly filterPortalSearchText = this.state.filterPortalSearchText;
  readonly cvAreaBadge = this.state.cvAreaBadge;

  readonly portalsSummaryLabel = computed(() => {
    const total = this.availablePortals.length;
    const selected = this.selectedPortalIds();
    if (selected.size === total) return `Todas as fontes (${total})`;
    if (selected.size === 0) return 'Nenhum portal selecionado';
    if (selected.size === 1) {
      const id = Array.from(selected)[0];
      const p = this.availablePortals.find((x) => x.id === id);
      return p ? p.name : id;
    }
    if (selected.size <= 2) {
      return Array.from(selected)
        .map((id) => this.availablePortals.find((x) => x.id === id)?.name || id)
        .join(', ');
    }
    return `${selected.size} portais selecionados`;
  });

  get filterText(): string { return this.state.filterText(); }
  set filterText(v: string) {
    this.state.filterText.set(v);
    this.state.persist();
  }

  get filterModel(): string { return this.state.filterModel(); }
  set filterModel(v: string) {
    this.state.filterModel.set(v);
    this.state.persist();
  }

  get filterRegion(): string { return this.state.filterRegion(); }
  set filterRegion(v: string) {
    this.state.filterRegion.set(v);
    this.state.persist();
  }

  get filterJobAge(): string { return this.state.filterJobAge(); }
  set filterJobAge(v: string) {
    this.state.filterJobAge.set(v);
    this.state.persist();
  }

  get filterScore(): string { return this.state.filterScore(); }
  set filterScore(v: string) {
    this.state.filterScore.set(v);
    this.state.persist();
  }

  get filterSort(): 'date' | 'score-desc' | 'score-asc' { return this.state.filterSort(); }
  set filterSort(v: 'date' | 'score-desc' | 'score-asc') {
    this.state.filterSort.set(v);
    this.state.persist();
  }

  get filterNoWarn(): boolean { return this.state.filterNoWarn(); }
  set filterNoWarn(v: boolean) {
    this.state.filterNoWarn.set(v);
    this.state.persist();
  }

  get filterHideUndated(): boolean { return this.state.filterHideUndated(); }
  set filterHideUndated(v: boolean) {
    this.state.filterHideUndated.set(v);
    this.state.persist();
  }

  get filterVisa(): boolean { return this.state.filterVisa(); }
  set filterVisa(v: boolean) {
    this.state.filterVisa.set(v);
    this.state.persist();
  }

  get autoMinScore(): number { return this.state.autoMinScore(); }
  set autoMinScore(v: number) {
    this.state.autoMinScore.set(Number(v) || 60);
    this.state.persist();
  }

  get autoContinuous(): boolean { return this.state.autoContinuous(); }
  set autoContinuous(v: boolean) {
    this.state.autoContinuous.set(Boolean(v));
    this.state.persist();
  }

  get autoCooldownMinutes(): number { return this.state.autoCooldownMinutes(); }
  set autoCooldownMinutes(v: number) {
    const n = Number(v);
    this.state.autoCooldownMinutes.set(Number.isNaN(n) ? 5 : n);
    this.state.persist();
  }

  @HostListener('document:click')
  onDocumentClick(): void {
    if (this.portalsDropdownOpen()) {
      this.portalsDropdownOpen.set(false);
    }
  }

  togglePortalsDropdown(event: MouseEvent): void {
    event.stopPropagation();
    this.portalsDropdownOpen.update((v) => !v);
  }

  isPortalSelected(id: string): boolean {
    return this.selectedPortalIds().has(id);
  }

  togglePortal(id: string, event?: Event): void {
    if (event) {
      event.stopPropagation();
    }
    const current = new Set(this.selectedPortalIds());
    if (current.has(id)) {
      current.delete(id);
    } else {
      current.add(id);
    }
    this.selectedPortalIds.set(current);
    this.state.persist();
    this.filterChange.emit();
  }

  selectAllPortals(): void {
    this.selectedPortalIds.set(new Set(this.availablePortals.map((p) => p.id)));
    this.state.persist();
    this.filterChange.emit();
  }

  deselectAllPortals(): void {
    this.selectedPortalIds.set(new Set());
    this.state.persist();
    this.filterChange.emit();
  }

  isCategoryFullySelected(catId: string): boolean {
    const inCat = this.availablePortals.filter((p) => p.category === catId);
    if (!inCat.length) return false;
    const sel = this.selectedPortalIds();
    return inCat.every((p) => sel.has(p.id));
  }

  toggleCategoryPortals(catId: string): void {
    const inCat = this.availablePortals.filter((p) => p.category === catId);
    const fullySelected = this.isCategoryFullySelected(catId);
    const current = new Set(this.selectedPortalIds());
    if (fullySelected) {
      inCat.forEach((p) => current.delete(p.id));
    } else {
      inCat.forEach((p) => current.add(p.id));
    }
    this.selectedPortalIds.set(current);
    this.state.persist();
    this.filterChange.emit();
  }

  getFilteredPortalsByCategory(catId: string): PortalOption[] {
    const q = this.filterPortalSearchText().trim().toLowerCase();
    const inCat = this.availablePortals.filter((p) => p.category === catId);
    if (!q) return inCat;
    return inCat.filter(
      (p) => p.name.toLowerCase().includes(q) || (p.badge && p.badge.toLowerCase().includes(q))
    );
  }

  hasMatchingPortalsInCategory(catId: string): boolean {
    return this.getFilteredPortalsByCategory(catId).length > 0;
  }
}
