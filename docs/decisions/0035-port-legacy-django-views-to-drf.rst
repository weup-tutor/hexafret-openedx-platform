Port Legacy Django Views to Django REST Framework
=================================================

:Status: Proposed
:Date: 2026-04-13
:Deciders: API Working Group
:Technical Story: Open edX REST API Standards - DRF adoption for legacy endpoints

Context
-------

Several older Open edX modules still use plain Django views rather than DRF views. These legacy
endpoints often manually handle HTTP methods, return hand-coded JSON instead of serializers, and
miss DRF features such as permission classes, throttling, authentication mixins, and automatic schema
generation.

This creates a fragmented API ecosystem with inconsistent behavior and limits OpenAPI generation.

Decision
--------

We will migrate legacy Django API views to **Django REST Framework** primitives:

* Prefer **ViewSets + Routers** for resource-style APIs.
* Use **APIView** for non-resource endpoints where ViewSets are not a good fit.

Migration rules:

* Replace manual method dispatch with DRF mixins/ViewSets (e.g., ``ListModelMixin``, ``CreateModelMixin``).
* Replace hand-coded JSON with DRF serializers for input/output (per ADR 0025).
* Ensure every migrated endpoint has machine-readable schema coverage via drf-spectacular decorators (per ADR 0027).
* Keep URLs stable where possible; if a breaking change is required, introduce a versioned endpoint and
  deprecate the old one.

Relevance in edx-platform
-------------------------

Legacy patterns that should be migrated:

* **Hand-coded JSON**: ``lms/djangoapps/edxnotes/views.py`` uses
  ``HttpResponse(json.dumps(notes_info, ...))`` and ``JsonResponseBadRequest({"error": ...})``
  instead of DRF serializers.
* **Django view + JsonResponse**: ``openedx/core/djangoapps/course_groups/views.py`` exposes
  ``json_http_response(data)``; ``cms/djangoapps/contentstore/views/block.py`` returns
  ``JsonResponse({"html": ..., "resources": ...})`` for xblock views.
* **Contentstore/Studio**: ``cms/djangoapps/contentstore/views/course.py`` and
  ``xblock_storage_handlers/view_handlers.py`` use function-based views with manual method
  dispatch; migrating these to ViewSets would enable schema generation and consistent auth.

Code examples
-------------

**Before (legacy Django view):**

.. code-block:: python

   from django.http import JsonResponse
   from django.views.decorators.http import require_GET

   @require_GET
   @login_required
   def notes(request, course_id):
       # ... manual parsing, no serializer, ad-hoc error shape
       return HttpResponse(json.dumps(notes_info, cls=NoteJSONEncoder),
                            content_type="application/json")

**After (DRF ViewSet + serializer):**

.. code-block:: python

   from rest_framework import viewsets
   from rest_framework.decorators import action
   from openedx.core.lib.api.view_utils import view_auth_classes

   @view_auth_classes()
   class NotesViewSet(viewsets.ReadOnlyModelViewSet):
       serializer_class = NotesSerializer
       permission_classes = [IsAuthenticated]

       def get_queryset(self):
           return get_notes_queryset(self.request, self.kwargs["course_id"])

       def list(self, request, *args, **kwargs):
           serializer = self.get_serializer(self.get_queryset(), many=True)
           return Response(serializer.data)

   # urls.py: router.register(r"notes", NotesViewSet, basename="notes")

**Non-resource endpoint (APIView):**

.. code-block:: python

   from rest_framework.views import APIView
   from rest_framework.response import Response

   @view_auth_classes()
   class HeartbeatView(APIView):
       def get(self, request):
           results = runchecks("extended" in request.GET)
           status_code = 200 if all(r["status"] for r in results.values()) else 503
           return Response(results, status=status_code)

Consequences
------------

Positive
~~~~~~~~

* Consistent request parsing, validation, and responses across services.
* Enables automated OpenAPI generation and improves documentation accuracy.
* Improves security and maintainability by leveraging DRF's standard patterns.

Negative / Trade-offs
~~~~~~~~~~~~~~~~~~~~~

* Upfront migration effort across multiple modules (certificates, discussions, enrollment, instructor, etc.).
* Risk of subtle behavior changes (status codes, error shapes, pagination) that must be covered with
  tests and deprecation messaging.

Alternatives Considered
-----------------------

* **Leave legacy endpoints as-is**: rejected due to missing DRF features and inconsistent responses.
* **Incremental wrappers around Django views**: rejected because wrappers don't reliably provide DRF
  capabilities like schema generation and standardized middleware integration.

Rollout Plan
------------

1. Perform an audit to identify endpoints still relying on legacy views and prioritize high-impact areas.
2. Create a reference implementation migration (one module) with agreed patterns and tests.
3. Migrate remaining modules iteratively, with continuous schema and contract testing.
4. Update and publish OpenAPI specs after each migration batch.

References
----------

* Open edX REST API Standards: "Overuse of Legacy Django Views Instead of DRF" and migration
  recommendations.
