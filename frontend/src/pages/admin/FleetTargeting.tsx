import { FC, FormEvent, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowLeft,
  Layers3,
  ListFilter,
  MapPin,
  Pencil,
  Plus,
  RefreshCw,
  Tags,
  Trash2,
} from 'lucide-react';
import {
  Badge,
  Button,
  Card,
  Input,
  Modal,
  Select,
  SkeletonTable,
  Table,
  useDialog, ErrorState } from '../../components/ui';
import {
  useAssignFleetWorkcellSite,
  useBulkFleetTagAssignments,
  useCreateFleetCohort,
  useCreateFleetGroup,
  useCreateFleetSite,
  useCreateFleetTag,
  useDeactivateFleetCohort,
  useDeactivateFleetGroup,
  useDeactivateFleetSite,
  useDeactivateFleetTag,
  useFleetCohort,
  useFleetCohorts,
  useFleetGroups,
  useFleetInventory,
  useFleetSites,
  useFleetTags,
  useFleetWorkcells,
  useUpdateFleetCohort,
  useUpdateFleetGroup,
  useUpdateFleetGroupMembers,
  useUpdateFleetSite,
  useUpdateFleetTag,
} from '../../hooks/useFleet';
import { handleApiError } from '../../api';
import {
  FleetCohort,
  FleetCohortOperator,
  FleetCohortQuery,
  FleetCohortUpdate,
  FleetNamedResource,
  FleetNamedUpdate,
  FleetTagUpdate,
} from '../../types/fleet';
import { formatDateTime, formatNumber } from '../../utils';

interface NamedForm {
  name: string;
  key: string;
  description: string;
}

interface TagForm extends NamedForm {
  color: string;
}

interface CohortForm {
  name: string;
  description: string;
  site_id: string;
  tag_id: string;
  group_id: string;
  collector_type: string;
  version_operator: '' | FleetCohortOperator;
  agent_version: string;
}

interface Feedback {
  tone: 'success' | 'error';
  message: string;
}

type EditKind = 'site' | 'tag' | 'group' | 'cohort';

interface EditTarget {
  kind: EditKind;
  id: string;
  name: string;
}

interface ResourceEditForm extends TagForm {
  query: string;
}

interface EditOriginal {
  resourceId: string;
  form: ResourceEditForm;
  cohortQuery?: FleetCohortQuery;
}

const emptyNamedForm: NamedForm = {
  name: '',
  key: '',
  description: '',
};

const emptyTagForm: TagForm = {
  ...emptyNamedForm,
  color: '#2dd4bf',
};

const emptyCohortForm: CohortForm = {
  name: '',
  description: '',
  site_id: '',
  tag_id: '',
  group_id: '',
  collector_type: '',
  version_operator: '',
  agent_version: '',
};

const emptyResourceEditForm: ResourceEditForm = {
  ...emptyTagForm,
  color: '',
  query: '',
};

const createPayload = (form: NamedForm) => ({
  name: form.name.trim(),
  key: form.key.trim() || undefined,
  description: form.description.trim() || undefined,
});

function namedUpdatePayload(
  form: ResourceEditForm,
  original: ResourceEditForm
): FleetNamedUpdate {
  const payload: FleetNamedUpdate = {};
  const name = form.name.trim();
  const key = form.key.trim();

  if (name !== original.name) payload.name = name;
  if (key !== original.key) payload.key = key;
  if (form.description !== original.description) {
    payload.description = form.description.trim() || null;
  }
  return payload;
}

function tagUpdatePayload(
  form: ResourceEditForm,
  original: ResourceEditForm
): FleetTagUpdate {
  const payload: FleetTagUpdate = namedUpdatePayload(form, original);
  if (form.color !== original.color) {
    payload.color = form.color.trim() || null;
  }
  return payload;
}

const ResourceList: FC<{
  kind: 'site' | 'tag' | 'group';
  items: FleetNamedResource[];
  emptyMessage: string;
  busy: boolean;
  onEdit: (item: FleetNamedResource) => void;
  onDeactivate: (item: FleetNamedResource) => void;
  accent?: (item: FleetNamedResource) => string | null;
}> = ({ kind, items, emptyMessage, busy, onEdit, onDeactivate, accent }) => {
  if (items.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-opsgrid-border p-4 text-center text-sm text-opsgrid-text-secondary">
        {emptyMessage}
      </p>
    );
  }

  return (
    <div className="divide-y divide-opsgrid-border rounded-lg border border-opsgrid-border">
      {items.map((item) => (
        <div key={item.id} className="flex items-start justify-between gap-3 p-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              {accent?.(item) && (
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full border border-opsgrid-border"
                  style={{ backgroundColor: accent(item) || undefined }}
                />
              )}
              <p className="truncate font-medium text-opsgrid-text">{item.name}</p>
              <Badge variant="neutral">{item.key}</Badge>
            </div>
            {item.description && (
              <p className="mt-1 text-sm text-opsgrid-text-secondary">{item.description}</p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              tooltip={`Edit ${item.name}`}
              aria-label={`Edit ${kind} ${item.name}`}
              onClick={() => onEdit(item)}
            >
              <Pencil size={15} />
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              tooltip={`Deactivate ${item.name}`}
              aria-label={`Deactivate ${item.name}`}
              onClick={() => onDeactivate(item)}
            >
              <Trash2 size={15} className="text-status-alarm" />
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
};

function cohortQuery(form: CohortForm): FleetCohortQuery | null {
  const clauses: FleetCohortQuery[] = [];
  if (form.site_id) {
    clauses.push({ field: 'site_id', operator: 'eq', value: form.site_id });
  }
  if (form.tag_id) {
    clauses.push({ field: 'tag', operator: 'any', value: [form.tag_id] });
  }
  if (form.group_id) {
    clauses.push({ field: 'group', operator: 'any', value: [form.group_id] });
  }
  if (form.collector_type.trim()) {
    clauses.push({
      field: 'collector_type',
      operator: 'eq',
      value: form.collector_type.trim(),
    });
  }
  if (form.version_operator && form.agent_version.trim()) {
    clauses.push({
      field: 'agent_version',
      operator: form.version_operator,
      value: form.agent_version.trim(),
    });
  }
  if (clauses.length === 0) return null;
  return clauses.length === 1 ? clauses[0] : { all_of: clauses };
}

export const FleetTargeting: FC = () => {
  const sites = useFleetSites();
  const workcells = useFleetWorkcells();
  const tags = useFleetTags();
  const groups = useFleetGroups();
  const cohorts = useFleetCohorts();
  const inventory = useFleetInventory();

  const createSite = useCreateFleetSite();
  const updateSite = useUpdateFleetSite();
  const deactivateSite = useDeactivateFleetSite();
  const assignWorkcellSite = useAssignFleetWorkcellSite();
  const createTag = useCreateFleetTag();
  const updateTag = useUpdateFleetTag();
  const deactivateTag = useDeactivateFleetTag();
  const bulkTags = useBulkFleetTagAssignments();
  const createGroup = useCreateFleetGroup();
  const updateGroup = useUpdateFleetGroup();
  const deactivateGroup = useDeactivateFleetGroup();
  const updateGroupMembers = useUpdateFleetGroupMembers();
  const createCohort = useCreateFleetCohort();
  const updateCohort = useUpdateFleetCohort();
  const deactivateCohort = useDeactivateFleetCohort();

  const [siteForm, setSiteForm] = useState<NamedForm>(emptyNamedForm);
  const [tagForm, setTagForm] = useState<TagForm>(emptyTagForm);
  const [groupForm, setGroupForm] = useState<NamedForm>(emptyNamedForm);
  const [cohortForm, setCohortForm] = useState<CohortForm>(emptyCohortForm);
  const [selectedAssets, setSelectedAssets] = useState<Set<string>>(new Set());
  const [selectedTagId, setSelectedTagId] = useState('');
  const [selectedGroupId, setSelectedGroupId] = useState('');
  const [search, setSearch] = useState('');
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const [editForm, setEditForm] = useState<ResourceEditForm>(emptyResourceEditForm);
  const [editOriginal, setEditOriginal] = useState<EditOriginal | null>(null);
  const [editError, setEditError] = useState<string | null>(null);

  const editingCohortId = editing?.kind === 'cohort' ? editing.id : '';
  const cohortDetail = useFleetCohort(editingCohortId);

  const siteItems = sites.data ?? [];
  const workcellItems = workcells.data ?? [];
  const tagItems = tags.data ?? [];
  const groupItems = groups.data ?? [];
  const cohortItems = cohorts.data ?? [];
  const inventoryItems = useMemo(
    () => inventory.data?.assets ?? [],
    [inventory.data?.assets]
  );

  const siteOptions = siteItems.map((site) => ({
    value: site.id,
    label: site.name,
  }));
  const tagOptions = tagItems.map((tag) => ({
    value: tag.id,
    label: tag.name,
  }));
  const groupOptions = groupItems.map((group) => ({
    value: group.id,
    label: group.name,
  }));

  const filteredAssets = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return inventoryItems;
    return inventoryItems.filter((asset) =>
      [
        asset.name,
        asset.id,
        asset.agent_id,
        asset.agent_version,
        asset.site_name,
        asset.workcell_name,
        asset.asset_type_name,
        ...asset.collector_types,
        ...asset.tags.map((tag) => tag.name),
        ...asset.groups.map((group) => group.name),
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query))
    );
  }, [inventoryItems, search]);

  const generatedCohortQuery = cohortQuery(cohortForm);
  const selectedCount = selectedAssets.size;
  const allVisibleSelected =
    filteredAssets.length > 0 &&
    filteredAssets.every((asset) => selectedAssets.has(asset.id));

  const editPending =
    editing?.kind === 'site'
      ? updateSite.isPending
      : editing?.kind === 'tag'
        ? updateTag.isPending
        : editing?.kind === 'group'
          ? updateGroup.isPending
          : editing?.kind === 'cohort'
            ? updateCohort.isPending
            : false;

  useEffect(() => {
    const cohort = cohortDetail.data;
    if (
      editing?.kind !== 'cohort' ||
      !cohort ||
      cohort.id !== editing.id ||
      cohortDetail.isFetching ||
      cohortDetail.isError ||
      editOriginal?.resourceId === editing.id
    ) {
      return;
    }

    const form: ResourceEditForm = {
      ...emptyResourceEditForm,
      name: cohort.name,
      description: cohort.description ?? '',
      query: JSON.stringify(cohort.query, null, 2),
    };
    setEditForm(form);
    setEditOriginal({
      resourceId: cohort.id,
      form,
      cohortQuery: cohort.query,
    });
  }, [
    cohortDetail.data,
    cohortDetail.isError,
    cohortDetail.isFetching,
    editOriginal?.resourceId,
    editing,
  ]);

  const reportError = (error: unknown) => {
    setFeedback({ tone: 'error', message: handleApiError(error).message });
  };

  const resetEditor = () => {
    setEditing(null);
    setEditForm(emptyResourceEditForm);
    setEditOriginal(null);
    setEditError(null);
  };

  const closeEditor = () => {
    if (!editPending) resetEditor();
  };

  const beginNamedEdit = (
    kind: 'site' | 'tag' | 'group',
    resource: FleetNamedResource,
    color: string | null = null
  ) => {
    const form: ResourceEditForm = {
      ...emptyResourceEditForm,
      name: resource.name,
      key: resource.key,
      description: resource.description ?? '',
      color: color ?? '',
    };
    setEditing({ kind, id: resource.id, name: resource.name });
    setEditForm(form);
    setEditOriginal({ resourceId: resource.id, form });
    setEditError(null);
    setFeedback(null);
  };

  const beginCohortEdit = (cohort: FleetCohort) => {
    setEditing({ kind: 'cohort', id: cohort.id, name: cohort.name });
    setEditForm({
      ...emptyResourceEditForm,
      name: cohort.name,
      description: cohort.description ?? '',
    });
    setEditOriginal(null);
    setEditError(null);
    setFeedback(null);
  };

  const reportEditError = (error: unknown) => {
    const message = handleApiError(error).message;
    setEditError(message);
  };

  const finishEdit = (kind: EditKind, name: string) => {
    resetEditor();
    setFeedback({ tone: 'success', message: `Updated ${kind} ${name}.` });
  };

  const submitEdit = (event: FormEvent) => {
    event.preventDefault();
    if (!editing || !editOriginal) return;

    setEditError(null);
    const name = editForm.name.trim();
    if (!name) {
      setEditError('Name is required.');
      return;
    }

    if (editing.kind === 'cohort') {
      let query: FleetCohortQuery;
      try {
        query = JSON.parse(editForm.query) as FleetCohortQuery;
      } catch {
        setEditError('Cohort query must be valid JSON.');
        return;
      }

      const payload: FleetCohortUpdate = {};
      if (name !== editOriginal.form.name) payload.name = name;
      if (editForm.description !== editOriginal.form.description) {
        payload.description = editForm.description.trim() || null;
      }
      if (JSON.stringify(query) !== JSON.stringify(editOriginal.cohortQuery)) {
        payload.query = query;
      }
      if (Object.keys(payload).length === 0) {
        setEditError('No changes to save.');
        return;
      }

      updateCohort.mutate(
        { cohortId: editing.id, payload },
        {
          onSuccess: (cohort) => finishEdit('cohort', cohort.name),
          onError: reportEditError,
        }
      );
      return;
    }

    const key = editForm.key.trim();
    if (!key) {
      setEditError('Key is required.');
      return;
    }

    if (editing.kind === 'site') {
      const payload = namedUpdatePayload(editForm, editOriginal.form);
      if (Object.keys(payload).length === 0) {
        setEditError('No changes to save.');
        return;
      }
      updateSite.mutate(
        { siteId: editing.id, payload },
        {
          onSuccess: (site) => finishEdit('site', site.name),
          onError: reportEditError,
        }
      );
      return;
    }

    if (editing.kind === 'tag') {
      const payload = tagUpdatePayload(editForm, editOriginal.form);
      if (Object.keys(payload).length === 0) {
        setEditError('No changes to save.');
        return;
      }
      updateTag.mutate(
        { tagId: editing.id, payload },
        {
          onSuccess: (tag) => finishEdit('tag', tag.name),
          onError: reportEditError,
        }
      );
      return;
    }

    const payload = namedUpdatePayload(editForm, editOriginal.form);
    if (Object.keys(payload).length === 0) {
      setEditError('No changes to save.');
      return;
    }
    updateGroup.mutate(
      { groupId: editing.id, payload },
      {
        onSuccess: (group) => finishEdit('group', group.name),
        onError: reportEditError,
      }
    );
  };

  const submitSite = (event: FormEvent) => {
    event.preventDefault();
    if (!siteForm.name.trim()) {
      setFeedback({ tone: 'error', message: 'Site name is required.' });
      return;
    }
    createSite.mutate(createPayload(siteForm), {
      onSuccess: (site) => {
        setSiteForm(emptyNamedForm);
        setFeedback({ tone: 'success', message: `Created site ${site.name}.` });
      },
      onError: reportError,
    });
  };

  const submitTag = (event: FormEvent) => {
    event.preventDefault();
    if (!tagForm.name.trim()) {
      setFeedback({ tone: 'error', message: 'Tag name is required.' });
      return;
    }
    createTag.mutate(
      { ...createPayload(tagForm), color: tagForm.color || undefined },
      {
        onSuccess: (tag) => {
          setTagForm(emptyTagForm);
          setFeedback({ tone: 'success', message: `Created tag ${tag.name}.` });
        },
        onError: reportError,
      }
    );
  };

  const submitGroup = (event: FormEvent) => {
    event.preventDefault();
    if (!groupForm.name.trim()) {
      setFeedback({ tone: 'error', message: 'Group name is required.' });
      return;
    }
    createGroup.mutate(createPayload(groupForm), {
      onSuccess: (group) => {
        setGroupForm(emptyNamedForm);
        setFeedback({ tone: 'success', message: `Created group ${group.name}.` });
      },
      onError: reportError,
    });
  };

  const submitCohort = (event: FormEvent) => {
    event.preventDefault();
    if (!cohortForm.name.trim()) {
      setFeedback({ tone: 'error', message: 'Cohort name is required.' });
      return;
    }
    if (
      Boolean(cohortForm.version_operator) !==
      Boolean(cohortForm.agent_version.trim())
    ) {
      setFeedback({
        tone: 'error',
        message: 'Choose both a version comparison and a semantic version.',
      });
      return;
    }
    if (!generatedCohortQuery) {
      setFeedback({
        tone: 'error',
        message: 'Choose at least one site, tag, group, collector, or version filter.',
      });
      return;
    }
    createCohort.mutate(
      {
        name: cohortForm.name.trim(),
        description: cohortForm.description.trim() || undefined,
        query: generatedCohortQuery,
      },
      {
        onSuccess: (cohort) => {
          setCohortForm(emptyCohortForm);
          setFeedback({ tone: 'success', message: `Created cohort ${cohort.name}.` });
        },
        onError: reportError,
      }
    );
  };

  const { confirm } = useDialog();

  const confirmDeactivate = async (
    kind: 'site' | 'tag' | 'group' | 'cohort',
    id: string,
    name: string
  ) => {
    // `DialogProvider` exists precisely for this, and its own docstring says why the
    // native one is wrong: `window.confirm` is unstyled, blocks the main thread, and is
    // SUPPRESSED ENTIRELY in some embedded and webview contexts — where a destructive
    // action then proceeds with no confirmation at all (FS-766).
    if (
      !(await confirm({
        title: `Deactivate ${kind}?`,
        message: `"${name}" will stop being applied to new rollouts.`,
        destructive: true,
        confirmLabel: 'Deactivate',
      }))
    )
      return;
    const options = {
      onSuccess: () =>
        setFeedback({ tone: 'success' as const, message: `Deactivated ${name}.` }),
      onError: reportError,
    };
    if (kind === 'site') deactivateSite.mutate(id, options);
    if (kind === 'tag') deactivateTag.mutate(id, options);
    if (kind === 'group') deactivateGroup.mutate(id, options);
    if (kind === 'cohort') deactivateCohort.mutate(id, options);
  };

  const toggleAsset = (assetId: string) => {
    setSelectedAssets((current) => {
      const next = new Set(current);
      if (next.has(assetId)) next.delete(assetId);
      else next.add(assetId);
      return next;
    });
  };

  const toggleAllVisible = () => {
    setSelectedAssets((current) => {
      const next = new Set(current);
      if (allVisibleSelected) {
        filteredAssets.forEach((asset) => next.delete(asset.id));
      } else {
        filteredAssets.slice(0, 500).forEach((asset) => next.add(asset.id));
      }
      return next;
    });
  };

  const updateTags = (operation: 'add' | 'remove') => {
    if (!selectedTagId || selectedCount === 0) {
      setFeedback({
        tone: 'error',
        message: 'Select a tag and at least one inventory asset.',
      });
      return;
    }
    if (selectedCount > 500) {
      setFeedback({ tone: 'error', message: 'Bulk tag changes are limited to 500 assets.' });
      return;
    }
    bulkTags.mutate(
      {
        tag_id: selectedTagId,
        asset_ids: Array.from(selectedAssets),
        operation,
      },
      {
        onSuccess: (result) => {
          setSelectedAssets(new Set());
          setFeedback({
            tone: 'success',
            message: `${operation === 'add' ? 'Added' : 'Removed'} tag on ${formatNumber(
              result.changed_count,
              0
            )} assets.`,
          });
        },
        onError: reportError,
      }
    );
  };

  const updateGroups = (operation: 'add' | 'remove') => {
    if (!selectedGroupId || selectedCount === 0) {
      setFeedback({
        tone: 'error',
        message: 'Select a group and at least one inventory asset.',
      });
      return;
    }
    if (selectedCount > 50) {
      setFeedback({
        tone: 'error',
        message: 'Group membership changes are limited to 50 assets per action.',
      });
      return;
    }
    updateGroupMembers.mutate(
      {
        group_id: selectedGroupId,
        asset_ids: Array.from(selectedAssets),
        operation,
      },
      {
        onSuccess: (result) => {
          setSelectedAssets(new Set());
          setFeedback({
            tone: 'success',
            message: `${operation === 'add' ? 'Added' : 'Removed'} ${formatNumber(
              result.changed_count,
              0
            )} group memberships.`,
          });
        },
        onError: reportError,
      }
    );
  };

  const refreshAll = () => {
    sites.refetch();
    workcells.refetch();
    tags.refetch();
    groups.refetch();
    cohorts.refetch();
    inventory.refetch();
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <Link
            to="/admin/fleet"
            className="mb-2 inline-flex items-center gap-1 rounded text-sm text-opsgrid-primary hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-opsgrid-primary"
          >
            <ArrowLeft size={16} /> Fleet OTA
          </Link>
          <h1 className="text-2xl font-bold text-opsgrid-text">Fleet Targeting</h1>
          <p className="text-sm text-opsgrid-text-secondary">
            Organize assets and save dynamic cohorts used by rollout previews.
          </p>
        </div>
        <Button variant="secondary" onClick={refreshAll}>
          <RefreshCw size={16} className="mr-2" />
          Refresh
        </Button>
      </div>

      {feedback && (
        <div
          role={feedback.tone === 'error' ? 'alert' : 'status'}
          className={
            feedback.tone === 'error'
              ? 'rounded-lg border border-status-alarm/40 bg-status-alarm/10 px-4 py-3 text-sm text-status-alarm'
              : 'rounded-lg border border-status-running/40 bg-status-running/10 px-4 py-3 text-sm text-opsgrid-text'
          }
        >
          {feedback.message}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card title="Sites" subtitle="Create location boundaries for workcells">
          <form className="space-y-3" onSubmit={submitSite}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Input
                label="Name"
                value={siteForm.name}
                onChange={(event) => setSiteForm({ ...siteForm, name: event.target.value })}
                placeholder="Plant A"
              />
              <Input
                label="Key"
                value={siteForm.key}
                onChange={(event) => setSiteForm({ ...siteForm, key: event.target.value })}
                placeholder="plant-a (auto if blank)"
              />
            </div>
            <Input
              label="Description"
              value={siteForm.description}
              onChange={(event) =>
                setSiteForm({ ...siteForm, description: event.target.value })
              }
              placeholder="Optional"
            />
            <div className="flex justify-end">
              <Button type="submit" size="sm" loading={createSite.isPending}>
                <Plus size={15} className="mr-2" /> Add site
              </Button>
            </div>
          </form>
          <div className="mt-4">
            <ResourceList
              kind="site"
              items={siteItems}
              emptyMessage="No sites configured."
              busy={deactivateSite.isPending || updateSite.isPending}
              onEdit={(site) => beginNamedEdit('site', site)}
              onDeactivate={(site) =>
                confirmDeactivate('site', site.id, site.name)
              }
            />
          </div>
        </Card>

        <Card title="Workcell locations" subtitle="Assign each existing workcell to a site">
          {workcells.isLoading && !workcells.data ? (
            <SkeletonTable rows={4} columns={2} />
          ) : workcellItems.length === 0 ? (
            <p className="text-sm text-opsgrid-text-secondary">No workcells available.</p>
          ) : (
            <div className="max-h-[25rem] overflow-auto rounded-lg border border-opsgrid-border">
              <Table>
                <Table.Head>
                  <Table.Row>
                    <Table.Header>Workcell</Table.Header>
                    <Table.Header>Site</Table.Header>
                  </Table.Row>
                </Table.Head>
                <Table.Body>
                  {workcellItems.map((workcell) => (
                    <Table.Row key={workcell.id}>
                      <Table.Cell>
                        <div className="font-medium">{workcell.name}</div>
                        <div className="text-xs text-opsgrid-text-secondary">
                          {workcell.location || 'No location'}
                        </div>
                      </Table.Cell>
                      <Table.Cell className="min-w-[13rem]">
                        <Select
                          aria-label={`Site for ${workcell.name}`}
                          value={workcell.site_id || ''}
                          disabled={assignWorkcellSite.isPending}
                          options={[
                            { value: '', label: 'Unassigned' },
                            ...siteOptions,
                          ]}
                          onChange={(event) =>
                            assignWorkcellSite.mutate(
                              {
                                workcellId: workcell.id,
                                siteId: event.target.value || null,
                              },
                              {
                                onSuccess: () =>
                                  setFeedback({
                                    tone: 'success',
                                    message: `Updated ${workcell.name}.`,
                                  }),
                                onError: reportError,
                              }
                            )
                          }
                        />
                      </Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table>
            </div>
          )}
        </Card>

        <Card title="Tags" subtitle="Reusable labels for dynamic filtering">
          <form className="space-y-3" onSubmit={submitTag}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_5rem]">
              <Input
                label="Name"
                value={tagForm.name}
                onChange={(event) => setTagForm({ ...tagForm, name: event.target.value })}
                placeholder="Video"
              />
              <Input
                label="Key"
                value={tagForm.key}
                onChange={(event) => setTagForm({ ...tagForm, key: event.target.value })}
                placeholder="video"
              />
              <Input
                label="Color"
                type="color"
                value={tagForm.color}
                onChange={(event) => setTagForm({ ...tagForm, color: event.target.value })}
                className="h-[42px] p-1"
              />
            </div>
            <Input
              label="Description"
              value={tagForm.description}
              onChange={(event) =>
                setTagForm({ ...tagForm, description: event.target.value })
              }
              placeholder="Optional"
            />
            <div className="flex justify-end">
              <Button type="submit" size="sm" loading={createTag.isPending}>
                <Plus size={15} className="mr-2" /> Add tag
              </Button>
            </div>
          </form>
          <div className="mt-4">
            <ResourceList
              kind="tag"
              items={tagItems}
              emptyMessage="No tags configured."
              busy={deactivateTag.isPending || updateTag.isPending}
              accent={(item) =>
                tagItems.find((tag) => tag.id === item.id)?.color || null
              }
              onEdit={(tag) =>
                beginNamedEdit(
                  'tag',
                  tag,
                  tagItems.find((item) => item.id === tag.id)?.color ?? null
                )
              }
              onDeactivate={(tag) => confirmDeactivate('tag', tag.id, tag.name)}
            />
          </div>
        </Card>

        <Card title="Groups" subtitle="Curated fleet membership managed by operators">
          <form className="space-y-3" onSubmit={submitGroup}>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Input
                label="Name"
                value={groupForm.name}
                onChange={(event) =>
                  setGroupForm({ ...groupForm, name: event.target.value })
                }
                placeholder="Plant A collectors"
              />
              <Input
                label="Key"
                value={groupForm.key}
                onChange={(event) =>
                  setGroupForm({ ...groupForm, key: event.target.value })
                }
                placeholder="plant-a-collectors"
              />
            </div>
            <Input
              label="Description"
              value={groupForm.description}
              onChange={(event) =>
                setGroupForm({ ...groupForm, description: event.target.value })
              }
              placeholder="Optional"
            />
            <div className="flex justify-end">
              <Button type="submit" size="sm" loading={createGroup.isPending}>
                <Plus size={15} className="mr-2" /> Add group
              </Button>
            </div>
          </form>
          <div className="mt-4">
            <ResourceList
              kind="group"
              items={groupItems}
              emptyMessage="No groups configured."
              busy={deactivateGroup.isPending || updateGroup.isPending}
              onEdit={(group) => beginNamedEdit('group', group)}
              onDeactivate={(group) =>
                confirmDeactivate('group', group.id, group.name)
              }
            />
          </div>
        </Card>
      </div>

      <Card
        title="Saved cohorts"
        subtitle="All selected filters are combined; membership re-resolves at preview time"
      >
        <form className="space-y-4" onSubmit={submitCohort}>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Input
              label="Name"
              value={cohortForm.name}
              onChange={(event) =>
                setCohortForm({ ...cohortForm, name: event.target.value })
              }
              placeholder="Plant A video agents below v2.1"
            />
            <Input
              label="Description"
              value={cohortForm.description}
              onChange={(event) =>
                setCohortForm({ ...cohortForm, description: event.target.value })
              }
              placeholder="Optional"
            />
            <Select
              label="Site"
              value={cohortForm.site_id}
              onChange={(event) =>
                setCohortForm({ ...cohortForm, site_id: event.target.value })
              }
              options={[{ value: '', label: 'Any site' }, ...siteOptions]}
            />
            <Select
              label="Tag"
              value={cohortForm.tag_id}
              onChange={(event) =>
                setCohortForm({ ...cohortForm, tag_id: event.target.value })
              }
              options={[{ value: '', label: 'Any tag' }, ...tagOptions]}
            />
            <Select
              label="Group"
              value={cohortForm.group_id}
              onChange={(event) =>
                setCohortForm({ ...cohortForm, group_id: event.target.value })
              }
              options={[{ value: '', label: 'Any group' }, ...groupOptions]}
            />
            <Input
              label="Collector type"
              value={cohortForm.collector_type}
              onChange={(event) =>
                setCohortForm({
                  ...cohortForm,
                  collector_type: event.target.value,
                })
              }
              placeholder="video"
            />
            <Select
              label="Agent version comparison"
              value={cohortForm.version_operator}
              onChange={(event) =>
                setCohortForm({
                  ...cohortForm,
                  version_operator: event.target.value as
                    | ''
                    | FleetCohortOperator,
                })
              }
              options={[
                { value: '', label: 'Any version' },
                { value: 'lt', label: 'Less than' },
                { value: 'lte', label: 'Less than or equal' },
                { value: 'eq', label: 'Equal to' },
                { value: 'gte', label: 'Greater than or equal' },
                { value: 'gt', label: 'Greater than' },
                { value: 'ne', label: 'Not equal to' },
              ]}
            />
            <Input
              label="Semantic version"
              value={cohortForm.agent_version}
              disabled={!cohortForm.version_operator}
              onChange={(event) =>
                setCohortForm({
                  ...cohortForm,
                  agent_version: event.target.value,
                })
              }
              placeholder="2.1.0"
            />
          </div>
          {generatedCohortQuery && (
            <pre className="max-h-36 overflow-auto rounded-lg border border-opsgrid-border bg-opsgrid-bg p-3 text-xs text-opsgrid-text-secondary">
              {JSON.stringify(generatedCohortQuery, null, 2)}
            </pre>
          )}
          <div className="flex justify-end">
            <Button type="submit" loading={createCohort.isPending}>
              <ListFilter size={16} className="mr-2" /> Save cohort
            </Button>
          </div>
        </form>

        <div className="mt-6 grid grid-cols-1 gap-3 lg:grid-cols-2">
          {cohortItems.length === 0 ? (
            <p className="rounded-lg border border-dashed border-opsgrid-border p-4 text-center text-sm text-opsgrid-text-secondary lg:col-span-2">
              No cohorts configured.
            </p>
          ) : (
            cohortItems.map((cohort) => (
              <div
                key={cohort.id}
                className="rounded-lg border border-opsgrid-border bg-opsgrid-bg p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="font-medium text-opsgrid-text">{cohort.name}</h3>
                    {cohort.description && (
                      <p className="mt-1 text-sm text-opsgrid-text-secondary">
                        {cohort.description}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={updateCohort.isPending || deactivateCohort.isPending}
                      tooltip={`Edit ${cohort.name}`}
                      aria-label={`Edit cohort ${cohort.name}`}
                      onClick={() => beginCohortEdit(cohort)}
                    >
                      <Pencil size={15} />
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      disabled={updateCohort.isPending || deactivateCohort.isPending}
                      tooltip={`Deactivate ${cohort.name}`}
                      aria-label={`Deactivate ${cohort.name}`}
                      onClick={() =>
                        confirmDeactivate('cohort', cohort.id, cohort.name)
                      }
                    >
                      <Trash2 size={15} className="text-status-alarm" />
                    </Button>
                  </div>
                </div>
                <pre className="mt-3 max-h-32 overflow-auto rounded border border-opsgrid-border p-2 text-xs text-opsgrid-text-secondary">
                  {JSON.stringify(cohort.query, null, 2)}
                </pre>
                <p className="mt-2 text-xs text-opsgrid-text-secondary">
                  Updated {cohort.updated_at ? formatDateTime(cohort.updated_at) : 'unknown'}
                </p>
              </div>
            ))
          )}
        </div>
      </Card>

      <Card
        title="Fleet inventory assignments"
        subtitle="Select assets, then apply tags or curated group membership"
        noPadding
        action={
          <Badge variant={selectedCount > 0 ? 'info' : 'neutral'}>
            {formatNumber(selectedCount, 0)} selected
          </Badge>
        }
      >
        <div className="space-y-3 border-b border-opsgrid-border p-4">
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(12rem,1fr)_minmax(11rem,0.7fr)_auto_minmax(11rem,0.7fr)_auto]">
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search assets, sites, versions, tags…"
              aria-label="Search fleet inventory"
            />
            <Select
              aria-label="Tag to apply"
              value={selectedTagId}
              onChange={(event) => setSelectedTagId(event.target.value)}
              options={tagOptions}
              placeholder={tagOptions.length ? 'Select tag' : 'No tags'}
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="secondary"
                loading={bulkTags.isPending}
                onClick={() => updateTags('add')}
              >
                Add
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={bulkTags.isPending}
                onClick={() => updateTags('remove')}
              >
                Remove
              </Button>
            </div>
            <Select
              aria-label="Group to apply"
              value={selectedGroupId}
              onChange={(event) => setSelectedGroupId(event.target.value)}
              options={groupOptions}
              placeholder={groupOptions.length ? 'Select group' : 'No groups'}
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="secondary"
                loading={updateGroupMembers.isPending}
                onClick={() => updateGroups('add')}
              >
                Add
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={updateGroupMembers.isPending}
                onClick={() => updateGroups('remove')}
              >
                Remove
              </Button>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-opsgrid-text-secondary">
            <span className="inline-flex items-center gap-1">
              <Tags size={13} /> Tag actions support up to 500 assets.
            </span>
            <span className="inline-flex items-center gap-1">
              <Layers3 size={13} /> Group actions support up to 50 assets per action.
            </span>
            <span className="inline-flex items-center gap-1">
              <MapPin size={13} /> Sites are inherited from each asset's workcell.
            </span>
          </div>
        </div>

        {inventory.isLoading && !inventory.data ? (
          <SkeletonTable rows={6} columns={7} />
        ) : inventory.isError ? (
          <ErrorState message="Failed to load fleet inventory."
            onRetry={() => inventory.refetch()}
            retrying={inventory.isFetching} />
        ) : filteredAssets.length === 0 ? (
          <div className="p-8 text-center text-sm text-opsgrid-text-secondary">
            No inventory assets match this search.
          </div>
        ) : (
          <Table>
            <Table.Head>
              <Table.Row>
                <Table.Header className="w-12">
                  <input
                    type="checkbox"
                    aria-label="Select all visible assets"
                    checked={allVisibleSelected}
                    onChange={toggleAllVisible}
                    className="h-4 w-4 rounded border-opsgrid-border"
                  />
                </Table.Header>
                <Table.Header>Asset</Table.Header>
                <Table.Header>Location</Table.Header>
                <Table.Header>Agent</Table.Header>
                <Table.Header>Collectors</Table.Header>
                <Table.Header>Tags</Table.Header>
                <Table.Header>Groups</Table.Header>
              </Table.Row>
            </Table.Head>
            <Table.Body>
              {filteredAssets.map((asset) => (
                <Table.Row key={asset.id}>
                  <Table.Cell>
                    <input
                      type="checkbox"
                      aria-label={`Select ${asset.name}`}
                      checked={selectedAssets.has(asset.id)}
                      onChange={() => toggleAsset(asset.id)}
                      className="h-4 w-4 rounded border-opsgrid-border"
                    />
                  </Table.Cell>
                  <Table.Cell>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{asset.name}</span>
                      <Badge variant={asset.is_active ? 'success' : 'neutral'}>
                        {asset.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </div>
                    <div className="font-mono text-xs text-opsgrid-text-secondary">
                      {asset.id}
                    </div>
                  </Table.Cell>
                  <Table.Cell>
                    <div>{asset.site_name || 'Unassigned site'}</div>
                    <div className="text-xs text-opsgrid-text-secondary">
                      {asset.workcell_name}
                    </div>
                  </Table.Cell>
                  <Table.Cell>
                    <div className="max-w-[12rem] truncate font-mono text-xs" title={asset.agent_id || undefined}>
                      {asset.agent_id || 'No agent ID'}
                    </div>
                    <div className="text-xs text-opsgrid-text-secondary">
                      v{asset.agent_version || 'unknown'}
                    </div>
                  </Table.Cell>
                  <Table.Cell>
                    <div className="flex max-w-xs flex-wrap gap-1">
                      {asset.collector_types.length > 0
                        ? asset.collector_types.map((collector) => (
                            <Badge key={collector} variant="neutral">
                              {collector}
                            </Badge>
                          ))
                        : '—'}
                    </div>
                  </Table.Cell>
                  <Table.Cell>
                    <div className="flex max-w-xs flex-wrap gap-1">
                      {asset.tags.length > 0
                        ? asset.tags.map((tag) => (
                            <Badge key={tag.id} variant="info">
                              {tag.name}
                            </Badge>
                          ))
                        : '—'}
                    </div>
                  </Table.Cell>
                  <Table.Cell>
                    <div className="flex max-w-xs flex-wrap gap-1">
                      {asset.groups.length > 0
                        ? asset.groups.map((group) => (
                            <Badge key={group.id} variant="neutral">
                              {group.name}
                            </Badge>
                          ))
                        : '—'}
                    </div>
                  </Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        )}
      </Card>

      <Modal
        isOpen={Boolean(editing)}
        onClose={closeEditor}
        closeOnBackdrop={!editPending}
        closeOnEscape={!editPending}
        title={editing ? `Edit ${editing.kind}` : 'Edit fleet resource'}
        description={
          editing
            ? `Update ${editing.name}. Only changed fields will be saved.`
            : undefined
        }
        footer={
          <>
            <Button
              type="button"
              variant="secondary"
              disabled={editPending}
              onClick={closeEditor}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              form="fleet-resource-edit-form"
              loading={editPending}
              disabled={
                !editOriginal ||
                (editing?.kind === 'cohort' && cohortDetail.isError)
              }
            >
              Save changes
            </Button>
          </>
        }
      >
        <form id="fleet-resource-edit-form" className="space-y-4" onSubmit={submitEdit}>
          {editError && (
            <div
              role="alert"
              className="rounded-lg border border-status-alarm/40 bg-status-alarm/10 px-3 py-2 text-sm text-status-alarm"
            >
              {editError}
            </div>
          )}

          <Input
            label="Name"
            required
            value={editForm.name}
            disabled={editPending || !editOriginal}
            onChange={(event) =>
              setEditForm({ ...editForm, name: event.target.value })
            }
          />

          {editing?.kind !== 'cohort' && (
            <Input
              label="Key"
              required
              value={editForm.key}
              disabled={editPending}
              onChange={(event) =>
                setEditForm({ ...editForm, key: event.target.value })
              }
            />
          )}

          <Input
            label="Description"
            value={editForm.description}
            disabled={editPending || !editOriginal}
            helperText="Leave blank to clear the description."
            onChange={(event) =>
              setEditForm({ ...editForm, description: event.target.value })
            }
          />

          {editing?.kind === 'tag' && (
            <Input
              label="Color"
              value={editForm.color}
              disabled={editPending}
              helperText="Use a CSS color value, or leave blank to clear it."
              onChange={(event) =>
                setEditForm({ ...editForm, color: event.target.value })
              }
            />
          )}

          {editing?.kind === 'cohort' && (
            <div>
              {cohortDetail.isError ? (
                <div
                  role="alert"
                  className="rounded-lg border border-status-alarm/40 bg-status-alarm/10 p-3 text-sm text-status-alarm"
                >
                  <p>Could not load the canonical cohort query.</p>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="mt-2"
                    onClick={() => cohortDetail.refetch()}
                  >
                    Retry
                  </Button>
                </div>
              ) : !editOriginal ? (
                <p role="status" className="text-sm text-opsgrid-text-secondary">
                  Loading the canonical cohort query…
                </p>
              ) : (
                <>
                  <label
                    htmlFor="fleet-cohort-query"
                    className="mb-1 block text-sm font-medium text-opsgrid-text"
                  >
                    Cohort query (JSON)
                  </label>
                  <textarea
                    id="fleet-cohort-query"
                    rows={10}
                    value={editForm.query}
                    disabled={editPending}
                    aria-describedby="fleet-cohort-query-help"
                    onChange={(event) =>
                      setEditForm({ ...editForm, query: event.target.value })
                    }
                    className="w-full rounded-lg border border-opsgrid-border bg-opsgrid-bg px-3 py-2 font-mono text-sm text-opsgrid-text focus:border-transparent focus:outline-none focus:ring-2 focus:ring-opsgrid-primary disabled:cursor-not-allowed disabled:opacity-50"
                  />
                  <p
                    id="fleet-cohort-query-help"
                    className="mt-1 text-sm text-opsgrid-text-secondary"
                  >
                    Nested queries are preserved unless this JSON is changed.
                  </p>
                </>
              )}
            </div>
          )}
        </form>
      </Modal>
    </div>
  );
};

export default FleetTargeting;
