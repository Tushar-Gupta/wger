# -*- coding: utf-8 -*-

# This file is part of wger Workout Manager.
#
# wger Workout Manager is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# wger Workout Manager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License

import logging
import uuid
import datetime
from calendar import HTMLCalendar

from django.shortcuts import render
from django.shortcuts import get_object_or_404
from django.http import HttpResponseRedirect
from django.http import HttpResponseForbidden
from django.core.cache import cache
from django.core.context_processors import csrf
from django.core.urlresolvers import reverse
from django.core.urlresolvers import reverse_lazy
from django.utils import formats
from django.utils.translation import ugettext as _
from django.utils.translation import ugettext_lazy
from django.forms.models import modelformset_factory
from django.views.generic import UpdateView
from django.views.generic import CreateView
from django.views.generic import DetailView
from django.views.generic import DeleteView

from wger.manager.models import Workout
from wger.manager.models import WorkoutSession
from wger.manager.models import Day
from wger.manager.models import WorkoutLog
from wger.manager.models import Schedule
from wger.manager.forms import HelperDateForm
from wger.manager.forms import HelperWorkoutSessionForm
from wger.manager.forms import WorkoutLogForm
from wger.utils.cache import cache_mapper
from wger.utils.generic_views import WgerFormMixin
from wger.utils.generic_views import WgerDeleteMixin
from wger.utils.generic_views import WgerPermissionMixin
from wger.weight.helpers import process_log_entries


logger = logging.getLogger('wger.custom')


# ************************
# Log functions
# ************************
class WorkoutLogUpdateView(WgerFormMixin, UpdateView, WgerPermissionMixin):
    '''
    Generic view to edit an existing workout log weight entry
    '''
    model = WorkoutLog
    form_class = WorkoutLogForm
    success_url = reverse_lazy('manager:workout:calendar')
    login_required = True

    def get_context_data(self, **kwargs):
        context = super(WorkoutLogUpdateView, self).get_context_data(**kwargs)
        context['form_action'] = reverse('manager:log:edit', kwargs={'pk': self.object.id})
        context['title'] = _(u'Edit log entry for %s') % self.object.exercise.name

        return context


class WorkoutLogAddView(WgerFormMixin, CreateView, WgerPermissionMixin):
    '''
    Generic view to add a new workout log weight entry
    '''
    model = WorkoutLog
    login_required = True
    form_class = WorkoutLogForm

    def dispatch(self, request, *args, **kwargs):
        '''
        Check for ownership
        '''
        workout = Workout.objects.get(pk=kwargs['workout_pk'])
        if workout.user != request.user:
            return HttpResponseForbidden()

        return super(WorkoutLogAddView, self).dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(WorkoutLogAddView, self).get_context_data(**kwargs)
        context['form_action'] = reverse('manager:log:add',
                                         kwargs={'workout_pk': self.kwargs['workout_pk']})
        context['title'] = _('New log entry')

        return context

    def get_success_url(self):
        return reverse('manager:log:log', kwargs={'pk': self.kwargs['workout_pk']})

    def form_valid(self, form):
        '''
        Set the workout and the user
        '''

        workout = Workout.objects.get(pk=self.kwargs['workout_pk'])
        form.instance.workout = workout
        form.instance.user = self.request.user
        return super(WorkoutLogAddView, self).form_valid(form)


class WorkoutLogDeleteView(WgerDeleteMixin, DeleteView, WgerPermissionMixin):
    '''
    Delete a workout log
    '''

    model = WorkoutLog
    success_url = reverse_lazy('manager:workout:calendar')
    title = ugettext_lazy('Delete workout log')
    form_action_urlname = 'manager:log:delete'
    login_required = True


def add(request, pk):
    '''
    Add a new workout log
    '''

    template_data = {}
    template_data.update(csrf(request))

    # Load the day and check ownership
    day = get_object_or_404(Day, pk=pk)
    if day.get_owner_object().user != request.user:
        return HttpResponseForbidden()

    # We need several lists here because we need to assign specific form to each
    # exercise: the entries for weight and repetitions have no indicator to which
    # exercise they belong besides the form-ID, from Django's formset
    counter = 0
    total_sets = 0
    exercise_list = {}
    form_to_exercise = {}

    for exercise_set in day.set_set.all():
        for exercise in exercise_set.exercises.all():

            # Maximum possible values
            total_sets += int(exercise_set.sets)
            counter_before = counter
            counter = counter + int(exercise_set.sets) - 1
            form_id_range = range(counter_before, counter + 1)

            # Add to list
            exercise_list[exercise.id] = {'obj': exercise,
                                          'sets': int(exercise_set.sets),
                                          'form_ids': form_id_range}

            counter += 1
            # Helper mapping form-ID <--> Exercise
            for id in form_id_range:
                form_to_exercise[id] = exercise

    # Define the formset here because now we know the value to pass to 'extra'
    WorkoutLogFormSet = modelformset_factory(WorkoutLog,
                                             form=WorkoutLogForm,
                                             exclude=('date', 'workout'),
                                             extra = total_sets)
    # Process the request
    if request.method == 'POST':

        # Make a copy of the POST data and go through it. The reason for this is
        # that the form expects a value for the exercise which is not present in
        # the form (for space and usability reasons)
        post_copy = request.POST.copy()

        for form_id in form_to_exercise:
            if post_copy.get('form-%s-weight' % form_id) or post_copy.get('form-%s-reps' % form_id):
                post_copy['form-%s-exercise' % form_id] = form_to_exercise[form_id].id

        # Pass the new data to the forms
        formset = WorkoutLogFormSet(data=post_copy)
        dateform = HelperDateForm(data=post_copy)
        session_form = HelperWorkoutSessionForm(data=post_copy)

        # If all the data is valid, save and redirect to log overview page
        if dateform.is_valid() and session_form.is_valid() and formset.is_valid():
            log_date = dateform.cleaned_data['date']

            if WorkoutSession.objects.filter(user=request.user, date=log_date).exists():
                session = WorkoutSession.objects.get(user=request.user, date=log_date)
                session_form = HelperWorkoutSessionForm(data=post_copy, instance=session)

            # Save the Workout Session only if there is not already one for this date
            instance = session_form.save(commit=False)
            if not WorkoutSession.objects.filter(user=request.user, date=log_date).exists():
                instance.date = log_date
                instance.user = request.user
                instance.workout = day.training
            else:
                session = WorkoutSession.objects.get(user=request.user, date=log_date)
                instance.instance = session
            instance.save()

            # Log entries
            instances = formset.save(commit=False)
            for instance in instances:

                instance.user = request.user
                instance.workout = day.training
                instance.date = log_date
                instance.save()

            return HttpResponseRedirect(reverse('manager:log:log', kwargs={'pk': day.training_id}))
    else:
        # Initialise the formset with a queryset that won't return any objects
        # (we only add new logs here and that seems to be the fastest way)
        formset = WorkoutLogFormSet(queryset=WorkoutLog.objects.none())

        dateform = HelperDateForm(initial={'date': formats.date_format(datetime.date.today(),
                                                                       "SHORT_DATE_FORMAT")})

        # Depending on whether there is already a workout session for today, update
        # the current one or create a new one (this will be the most usual case)
        if WorkoutSession.objects.filter(user=request.user, date=datetime.date.today()).exists():
            session = WorkoutSession.objects.get(user=request.user, date=datetime.date.today())
            session_form = HelperWorkoutSessionForm(instance=session)
        else:
            session_form = HelperWorkoutSessionForm()

    # Pass the correct forms to the exercise list
    for exercise in exercise_list:

        form_id_from = min(exercise_list[exercise]['form_ids'])
        form_id_to = max(exercise_list[exercise]['form_ids'])
        exercise_list[exercise]['forms'] = formset[form_id_from:form_id_to + 1]

    template_data['day'] = day
    template_data['exercises'] = exercise_list
    template_data['exercise_list'] = exercise_list
    template_data['formset'] = formset
    template_data['dateform'] = dateform
    template_data['session_form'] = session_form
    template_data['form_action'] = reverse('manager:day:log', kwargs={'pk': pk})

    return render(request, 'day/log.html', template_data)


class WorkoutLogDetailView(DetailView, WgerPermissionMixin):
    '''
    An overview of the workout's log
    '''

    model = Workout
    template_name = 'workout/log.html'
    login_required = True
    context_object_name = 'workout'

    def get_context_data(self, **kwargs):

        # Call the base implementation first to get a context
        context = super(WorkoutLogDetailView, self).get_context_data(**kwargs)

        # Prepare the entries for rendering and the D3 chart
        workout_log = {}

        for day_list in self.object.canonical_representation['day_list']:
            day_id = day_list['obj'].id
            workout_log[day_id] = {}
            for set_list in day_list['set_list']:
                exercise_log = {}
                for exercise_list in set_list['exercise_list']:
                    exercise_id = exercise_list['obj'].id
                    exercise_log[exercise_id] = []

                    logs = exercise_list['obj'].workoutlog_set.filter(user=self.request.user,
                                                                      workout=self.object)
                    entry_log, chart_data = process_log_entries(logs)
                    if entry_log:
                        exercise_log[exercise_list['obj'].id].append(entry_log)

                    if exercise_log:
                        workout_log[day_id][exercise_id] = {}
                        workout_log[day_id][exercise_id]['log_by_date'] = entry_log
                        workout_log[day_id][exercise_id]['div_uuid'] = 'div-' + str(uuid.uuid4())
                        workout_log[day_id][exercise_id]['chart_data'] = chart_data

        context['workout_log'] = workout_log
        context['reps'] = _("Reps")

        return context

    def dispatch(self, request, *args, **kwargs):
        '''
        Check for ownership
        '''

        workout = Workout.objects.get(pk=kwargs['pk'])
        if workout.user != request.user:
            return HttpResponseForbidden()

        # Dispatch normally
        return super(WorkoutLogDetailView, self).dispatch(request, *args, **kwargs)


class WorkoutCalendar(HTMLCalendar):
    '''
    A calendar renderer, see this blog entry for details:
    * http://uggedal.com/journal/creating-a-flexible-monthly-calendar-in-django/
    '''
    def __init__(self, workout_logs, *args, **kwargs):
        super(WorkoutCalendar, self).__init__(*args, **kwargs)
        self.workout_logs = workout_logs

    def formatday(self, day, weekday):
        if day != 0:
            cssclass = self.cssclasses[weekday]
            date_obj = datetime.date(self.year, self.month, day)
            if datetime.date.today() == date_obj:
                cssclass += ' today'
            if day in self.workout_logs:
                current_log = self.workout_logs.get(day)
                if current_log['impression'] == WorkoutSession.IMPRESSION_BAD:
                    background_css = 'btn-danger'
                elif current_log['impression'] == WorkoutSession.IMPRESSION_GOOD:
                    background_css = 'btn-success'
                else:
                    background_css = 'btn-warning'

                url = reverse('manager:log:log', kwargs={'pk': current_log['log'].workout_id})
                formatted_date = date_obj.strftime('%Y-%m-%d')
                body = []
                body.append('<a href="{0}"'
                            'data-log="log-{1}"'
                            'class="btn btn-block {2} calendar-link">'.format(url,
                                                                              formatted_date,
                                                                              background_css))
                body.append(repr(day))
                body.append('</a>')
                return self.day_cell(cssclass, '{0}'.format(''.join(body)))
            return self.day_cell(cssclass, day)
        return self.day_cell('noday', '&nbsp;')

    def formatmonth(self, year, month):
        '''
        Format the table header. This is basically the same code from python's
        calendar module but with additional bootstrap classes
        '''
        self.year, self.month = year, month
        out = []
        out.append('<table class="month table table-bordered">\n')
        out.append(self.formatmonthname(year, month))
        out.append('\n')
        out.append(self.formatweekheader())
        out.append('\n')
        for week in self.monthdays2calendar(year, month):
            out.append(self.formatweek(week))
            out.append('\n')
        out.append('</table>\n')
        return ''.join(out)

    def day_cell(self, cssclass, body):
        '''
        Renders a day cell
        '''
        return '<td class="{0}" style="vertical-align: middle;">{1}</td>'.format(cssclass, body)


def calendar(request, year=None, month=None):
    '''
    Show a calendar with all the workout logs
    '''
    if not year:
        year = datetime.date.today().year
    else:
        year = int(year)
    if not month:
        month = datetime.date.today().month
    else:
        month = int(month)

    context = {}
    logs = WorkoutLog.objects.filter(user=request.user,
                                     date__year=year,
                                     date__month=month).order_by('exercise')
    logs_filtered = cache.get(cache_mapper.get_workout_log(request.user.pk, year, month))
    if not logs_filtered:
        logs_filtered = {}

        # Process the logs. Group by date and check for impressions
        for log in logs:
            if log.date not in logs_filtered:
                session = log.get_workout_session()

                if session:
                    impression = session.impression
                else:
                    # Default is 'neutral'
                    impression = WorkoutSession.IMPRESSION_NEUTRAL

                logs_filtered[log.date.day] = {'impression': impression,
                                               'log': log}
        cache.set(cache_mapper.get_workout_log(request.user.pk, year, month), logs_filtered)

    (current_workout, schedule) = Schedule.objects.get_current_workout(request.user)
    context['calendar'] = WorkoutCalendar(logs_filtered).formatmonth(year, month)
    context['logs'] = process_log_entries(logs)[0]
    context['current_year'] = year
    context['current_month'] = month
    context['current_workout'] = current_workout
    context['impressions'] = WorkoutSession.IMPRESSION
    context['month_list'] = WorkoutLog.objects.filter(user=request.user).dates('date', 'month')
    return render(request, 'workout/calendar.html', context)
