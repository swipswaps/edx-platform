"""
@@TODO doc
"""
from textwrap import dedent

from django.core.management.base import BaseCommand
from opaque_keys.edx.keys import CourseKey
from opaque_keys.edx.locator import LibraryLocator
from organizations.api import bulk_add_organization_courses, bulk_add_organizations
from organizations.models import Organization, OrganizationCourse

from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.split_mongo.split import SplitMongoModuleStore


class Command(BaseCommand):
    """
    @@TODO doc
    """
    help = dedent(__doc__).strip()

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help="Apply backfill to database (instead of just showing)."
        )
        parser.add_argument(
            '--dry',
            action='store_true',
            help="Apply backfill to database (instead of just showing)."
        )

    def handle(self, *args, **options):

        # Find `orgs` and `org_coursekey_pairs` to be bulk-added.
        orgslug_coursekey_pairs = find_orgslug_coursekey_pairs()
        orgslug_library_pairs = find_orgslug_library_pairs(get_split_modulestore())
        orgslugs = sorted(
            {orgslug for orgslug, _ in orgslug_coursekey_pairs} |
            {orgslug for orgslug, _ in orgslug_library_pairs}
        )
        orgs_by_slug = {
            orgslug: {
                "short_name": orgslug,
                "name": orgslug,
            } for orgslug in orgslugs
        }
        org_coursekey_pairs = [
            (orgs_by_slug[orgslug], coursekey)
            for orgslug, coursekey in orgslug_coursekey_pairs
        ]
        orgs = orgs_by_slug.values()

        # Note that edx-organizations code will handle:
        # * Not overwriting existing organizations.
        # * Skipping duplicates, based on the short name (case-INsensiive).

        # Start with a dry run.
        # This will log to the user which orgs/org-courses will be created/reactivated.
        bulk_add_organizations(orgs, dry_run=True)
        bulk_add_organization_courses(org_coursekey_pairs, dry_run=True)
        if not should_apply_changes(options):
            print("No changes applied.")
            return

        # It's go time.
        print("Applying changes...")
        bulk_add_organizations(orgs)
        bulk_add_organization_courses(org_coursekey_pairs)
        print("Changes applied successfully.")


def should_apply_changes(options):
    """
    Should we apply the changes to the db?

    If already specified on the command line, use that value.

    Otherwise, prompt.
    """
    if options.get('apply') and options.get('dry'):
        raise CommandError("Only one of 'apply' and 'dry' may be specified")
    if options.get('apply'):
        return True
    if options.get('dry'):
        return False
    answer = ""
    while answer.lower() not in {'y', 'yes', 'n', 'no'}:
        answer = input('Commit changes shown above to the database [y/n]? ')
    return answer.lower().startswith('y')


def get_split_modulestore():
    """
    Reach into the Mixed module store and return the Split module store.

    This will raise an Exception if there is no SplitMongoModuleStore instance
    within the Mixed store.

    Returns: SplitMongoModuleStore
    """
    for store in modulestore().modulestores:
        if isinstance(store, SplitMongoModuleStore):
            return store
    raise Exception(
        "No instances of SplitMongoModuleStore found in modulestore().modulestores. "
        "A SplitMongoModuleStore instance is needed to run this command."
    )


def find_orgslug_coursekey_pairs():
    """
    Returns the (case-sensitively) unique pairs of
    (organization slug course run key) from the CourseOverviews table,
    which should contain all course runs in the system.

    Returns: set[tuple[str, CourseKey]]
    """
    # Using a set comprehension removes any duplicate (org, id) pairs.
    return {
        (
            org_slug,
            course_key,
        )
        for org_slug, course_key
        # Worth noting: This will load all CourseOverviews, no matter their VERSION.
        # This is intentional: there may be course runs that haven't updated
        # their CourseOverviews entry since the last schema change; we still want
        # capture those course runs.
        in CourseOverview.objects.all().values_list("org", "id")
        # Skip any entries with the bogus default 'org' value.
        # It would only be there for *very* outdated course overviews--there
        # should be none on edx.org, but they could plausibly exist in the community.
        if org_slug != "outdated_entry"
    }


def find_orgslug_library_pairs(split_modulestore):
    """
    Returns the (case-insensitively) unique pairs of
    (organization short name, content library key)
    from the 'library' branch of the Split module store index,
    which should contain all modulestore-based content libraries in the system.

    Note that this only considers "version 1" (aka "legacy" or "modulestore-based")
    content libraries.
    We do not consider "version 2" (aka "blockstore-based") content libraries,
    because those require a database-level link to their authoring organization,
    and thus would not need backfilling via this command.

    Arguments:
        split_modulestore (SplitMongoModuleStore)

    Returns: set[tuple[str, LibraryLocator]]
    """
    return {
        # library_index["course"] is actually the 'library slug',
        # which along with the 'org slug', makes up the library's key.
        # It is in the "course" field because the DB schema was designed
        # before content libraries were envisioned.
        (
            library_index["org"],
            LibraryLocator(library_index["org"], library_index["course"]),
        )
        for library_index
        # Again, 'course' here refers to course-like objects, which includes
        # content libraries. By specifying branch="library", we're filtering for just
        # content libraries.
        in split_modulestore.find_matching_course_indexes(branch="library")
    }
